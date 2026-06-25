import pandas as pd
import time
import json
import os
import google.generativeai as genai


class TransactionPipeline:
    def __init__(self, llm_client=None):
        """Initialize transaction pipeline."""

        api_key = os.getenv("GEMINI_API_KEY")

        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel("gemini-2.0-flash")
        else:
            self.model = None

        self.allowed_categories = [
            "Food",
            "Shopping",
            "Travel",
            "Transport",
            "Utilities",
            "Cash Withdrawal",
            "Entertainment",
            "Other"
        ]

    # ==========================================================================
    # STEP A: DATA CLEANING (Pandas Engine)
    # ==========================================================================
    def clean_data(self, csv_file_path) -> pd.DataFrame:
        """
        Loads the dirty CSV, normalizes formats, handles casing, and drops exact duplicates.
        """
        # Load dataset
        df = pd.read_csv(csv_file_path)
        
        # 1. Remove exact duplicate rows
        df = df.drop_duplicates().reset_index(drop=True)
        
        # 2. Normalize Date Formats to ISO 8601 (YYYY-MM-DD)
        df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.strftime('%Y-%m-%d')
        
        # 3. Strip Currency Symbols ($ or commas) and force numeric Float casting
        if df['amount'].dtype == object:
            df['amount'] = df['amount'].astype(str).str.replace(r'[\$,]', '', regex=True)
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0.0)
        
        # 4. Uppercase status values & handle inconsistent casing
        df['status'] = df['status'].astype(str).str.upper().str.strip()
        
        # 5. Uppercase currency to standardize (INR/USD)
        df['currency'] = df['currency'].astype(str).str.upper().str.strip()
        
        # 6. Fill missing spending categories with 'Uncategorised'
        df['category'] = df['category'].fillna('Uncategorised').astype(str).str.strip()
        
        return df

    # ==========================================================================
    # STEP B: ANOMALY DETECTION (Statistical Outliers & Brand Mismatch)
    # ==========================================================================
    def detect_anomalies(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Flags statistical outliers (3x account median) and currency/brand mismatches.
        """
        df['is_anomaly'] = False
        df['anomaly_reason'] = ""

        # 1. Flag transactions where amount exceeds 3x the account's median
        account_medians = df.groupby('account_id')['amount'].median()
        
        for index, row in df.iterrows():
            acc_id = row['account_id']
            median = account_medians.get(acc_id, 0.0)
            
            # Outlier Trigger Condition
            if row['amount'] > (3 * median) and median > 0:
                df.at[index, 'is_anomaly'] = True
                df.at[index, 'anomaly_reason'] = f"Statistical Outlier (Exceeded 3x Median: {median})"
                continue

            # 2. Domestic Brand vs USD Currency Mismatch Check
            domestic_brands = ['Swiggy', 'Ola', 'IRCTC']
            if row['currency'] == 'USD' and any(brand in str(row['merchant']) for brand in domestic_brands):
                df.at[index, 'is_anomaly'] = True
                df.at[index, 'anomaly_reason'] = "Currency Mismatch: Domestic brand transacted in USD"

        return df

    # ==========================================================================
    # STEP C: BATCH LLM CLASSIFICATION (Optimized Array Parsing)
    # ==========================================================================
    def classify_missing_categories_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Batches unclassified or 'Uncategorised' rows to classify them via a single LLM call.
        """
        # Find rows that need classification
        mask_needed = (df['category'] == 'Uncategorised') | (df['category'] == '')
        missing_df = df[mask_needed]
        
        if missing_df.empty:
            return df

        df['llm_category'] = None
        df['llm_failed'] = False

        # Prepare payload batch: Grouping indices and text targets
        batch_items = []
        for idx, row in missing_df.iterrows():
            
            batch_items.append({
                    "id": int(idx),
                    "merchant": str(row.get("merchant", "")),
                    "notes": str(row.get("notes", ""))
                })

        # Strict Prompt Engineering Matrix for JSON output compliance
        prompt = f"""
        You are a financial backend data analyst parsing transactions.
        Classify each transaction into exactly one of these categories: {self.allowed_categories}.

        Input Data JSON Array:
        {json.dumps(batch_items)}

        Respond STRICTLY with a valid JSON array of objects, containing 'id' and 'category' keys only.
        Example format: [{{"id": 0, "category": "Food"}}]
        """

        max_retries = 3

       
        for attempt in range(max_retries):
            try:
                if not self.model:
                    raise Exception("Gemini API key not configured")

                # Using generation_config to natively enforce JSON response structure
                response = self.model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"}
                )

                raw_json = response.text.strip()
                predictions = json.loads(raw_json)

                for pred in predictions:
                    target_idx = pred["id"]
                    assigned_cat = pred["category"]

                    if assigned_cat in self.allowed_categories:
                        df.at[target_idx, "category"] = assigned_cat
                        df.at[target_idx, "llm_category"] = assigned_cat

                break  # Break loop if successful

            except Exception as e:
                if attempt == max_retries - 1:
                    df.loc[mask_needed, "llm_failed"] = True
                    print(f"Category classification failed: {e}")
                else:
                    time.sleep(2 ** attempt)
                    
        return df

    # ==========================================================================
    # STEP D: LLM NARRATIVE SUMMARY REPORT GENERATOR
    # ==========================================================================
    def generate_narrative_summary(self, df: pd.DataFrame) -> dict:
        """
        Executes a single master LLM call to generate a structured spending summary JSON.
        """
        # Calculate financial aggregations dynamically to feed into the prompt context
        spend_summary = df.groupby(['currency', 'status'])['amount'].sum().to_dict()
        anomaly_count = int(df['is_anomaly'].sum())
        top_merchants = df['merchant'].value_counts().head(3).index.tolist()

        # Prompt construction compiling high-level stats
        prompt = f"""
        Generate a structured financial report narrative summary based on these aggregations.
        Total Spend Matrix (Currency, Status): {str(spend_summary)}
        Flagged Anomalies Count: {anomaly_count}
        Top 3 Merchants: {str(top_merchants)}

        Respond STRICTLY with a JSON object matching this exact structural schema:
        {{
            "total_spend_inr": float,
            "total_spend_usd": float,
            "top_merchants": ["string", "string", "string"],
            "anomaly_count": int,
            "narrative": "A 2-3 sentence spending narrative overview goes here.",
            "risk_level": "low"
        }}
        """
        
        
        if not self.model:
            raise Exception("Gemini API key not configured")

        response = self.model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )

        raw_json = response.text.strip()
        summary_report = json.loads(raw_json)

        return summary_report