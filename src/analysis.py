import pandas as pd
import requests
import os
from pathlib import Path
from datetime import datetime, timedelta

# Required secret: fail fast if missing instead of embedding credentials.
DAILY_ACTIVITY_API_KEY = os.environ["DAILY_ACTIVITY_API_KEY"]

# ============================================================
# HELPERS (same as other files)
# ============================================================
def get_last_week():
    today = datetime.now().date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_friday = last_monday + timedelta(days=4)
    return last_monday, last_friday

def get_week_folder():
    start, end = get_last_week()
    return f"{start}_{end}"

def normalize(col):
    return (col - col.min()) / (col.max() - col.min() + 1e-9)


# ============================================================
# MAIN FUNCTION
# ============================================================
def run_analysis():
    print("\n🚀 Starting analysis...\n")

    # ============================================================
    # STEP 1: FETCH PROMPT QUALITY (UNCHANGED LOGIC)
    # ============================================================
    print("Fetching prompt quality data...\n")

    url = "https://prompts.yorkdevs.link/api/v1/users/daily-activity"

    headers = {
        "x-api-key": DAILY_ACTIVITY_API_KEY,
        "Content-Type": "application/json"
    }

    start, end = get_last_week()

    payload = {
        "startDate": str(start),
        "endDate": str(end)
    }

    response = requests.post(url, headers=headers, json=payload)
    raw = response.json()

    if isinstance(raw, dict):
        if "data" in raw:
            data = raw["data"]
        elif "result" in raw and "items" in raw["result"]:
            data = raw["result"]["items"]
        else:
            raise Exception("Unexpected API format")
    else:
        data = raw

    df_api = pd.DataFrame(data)

    avg_col = [c for c in df_api.columns if "avg" in c.lower()][0]
    prompt_col = [c for c in df_api.columns if "prompt" in c.lower()][0]

    df_api[avg_col] = pd.to_numeric(df_api[avg_col], errors="coerce")
    df_api[prompt_col] = pd.to_numeric(df_api[prompt_col], errors="coerce")

    quality = (
        df_api.groupby("email")
        .apply(lambda x: pd.Series({
            "total_prompts": x[prompt_col].sum(),
            "quality_score": round(
                (x[avg_col] * x[prompt_col]).sum() / x[prompt_col].sum(), 2
            )
        }))
        .reset_index()
    )

    # ============================================================
    # STEP 2: LOAD MERGED DATA
    # ============================================================
    print("\nLoading merged usage data...\n")

    week_folder = get_week_folder()

    INPUT_FILE = Path(f"data/processed/{week_folder}/merged.csv")
    OUTPUT_FILE = Path(f"data/processed/{week_folder}/top10.csv")
    ALL_USERS_FILE = Path(f"data/processed/{week_folder}/all_users.csv")

    if not INPUT_FILE.exists():
        raise Exception(f"❌ Missing merged file: {INPUT_FILE}")

    df = pd.read_csv(INPUT_FILE)

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])

    df["Ai Lines"] = pd.to_numeric(df["Ai Lines"], errors="coerce").fillna(0)
    df["Total Tokens"] = pd.to_numeric(df["Total Tokens"], errors="coerce").fillna(0)
    df["Cost"] = pd.to_numeric(df["Cost"], errors="coerce").fillna(0)

    # ============================================================
    # STEP 3: USAGE METRICS (UNCHANGED)
    # ============================================================
    print("\nCalculating enhanced usage metrics...\n")

    user_usage = (
        df.groupby(["Email", "Name"], as_index=False)
        .agg(
            Active_Days=("Date", lambda x: x.dt.date.nunique()),
            Total_AI_Lines=("Ai Lines", "max"),
            Total_Tokens=("Total Tokens", "sum"),
            Total_Cost=("Cost", "sum"),
            Total_Prompts=("Email", "count"),
            Unique_Models=("Model", lambda x: x.nunique()),
            Non_Auto_Usage=("Model", lambda x: (x != "auto").sum())
        )
    )

    user_usage["Non_Auto_Percentage"] = (
        user_usage["Non_Auto_Usage"] / user_usage["Total_Prompts"]
    ).fillna(0)

    TOTAL_CREDITS = 20
    user_usage["Credit_Utilization"] = (
        user_usage["Total_Cost"] / TOTAL_CREDITS
    ).clip(upper=1)

    user_usage["AI_norm"] = normalize(user_usage["Total_AI_Lines"])
    user_usage["Active_norm"] = normalize(user_usage["Active_Days"])
    user_usage["Token_norm"] = normalize(user_usage["Total_Tokens"])
    user_usage["Model_norm"] = normalize(user_usage["Non_Auto_Percentage"])
    user_usage["Credit_norm"] = normalize(user_usage["Credit_Utilization"])

    user_usage["usage_score"] = (
        0.60 * user_usage["AI_norm"] +
        0.10 * user_usage["Active_norm"] +
        0.10 * user_usage["Token_norm"] +
        0.10 * user_usage["Model_norm"] +
        0.10 * user_usage["Credit_norm"]
    ).round(3)

    # ============================================================
    # STEP 4: MERGE WITH QUALITY
    # ============================================================
    final_df = user_usage.merge(
        quality,
        left_on="Email",
        right_on="email",
        how="inner"
    )

    final_df["quality_norm"] = normalize(final_df["quality_score"]).round(3)

    final_df["final_score"] = (
        0.5 * final_df["usage_score"] +
        0.5 * final_df["quality_norm"]
    ).round(3)

    final_df["usage_score"] = (final_df["usage_score"] * 100).round(2)
    final_df["quality_norm"] = (final_df["quality_norm"] * 100).round(2)
    final_df["final_score"] = (final_df["final_score"] * 100).round(2)


    MIN_AI_LINES = final_df["Total_AI_Lines"].quantile(0.50)   # dynamic
    MIN_COST = 10
    MIN_PROMPTS = 20

    eligible_users = final_df[
        (final_df["Total_AI_Lines"] >= MIN_AI_LINES) &
        (final_df["Total_Cost"] >= MIN_COST) &
        (final_df["Total_Prompts"] >= MIN_PROMPTS)
    ]

    # keep eligible users
    eligible = eligible_users.copy().sort_values("final_score", ascending=False)

    # remove already included users from final_df
    remaining = final_df[~final_df['email'].isin(eligible_users['email'])].sort_values("final_score", ascending=False)

    # combine
    all_users = pd.concat([eligible, remaining], ignore_index=True)

    ALL_USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    all_users.to_csv(ALL_USERS_FILE, index=False)

    top_10 = eligible.head(10)

    # ============================================================
    # STEP 5: SAVE OUTPUT
    # ============================================================
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    top_10.to_csv(OUTPUT_FILE, index=False)

    print(f"\n✅ Top 10 saved → {OUTPUT_FILE}\n")

    return OUTPUT_FILE


# ============================================================
# RUN STANDALONE
# ============================================================
if __name__ == "__main__":
    run_analysis()
