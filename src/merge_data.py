import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# -----------------------------
# SAME helper as downloader
# -----------------------------
def get_last_week():
    today = datetime.now().date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_friday = last_monday + timedelta(days=4)
    return last_monday, last_friday

def get_week_folder():
    start, end = get_last_week()
    return f"{start}_{end}"


# -----------------------------
# MAIN MERGE FUNCTION
# -----------------------------
def run_merge():
    week_folder = get_week_folder()

    RAW_DIR = Path(f"data/raw/{week_folder}")
    PROCESSED_DIR = Path(f"data/processed/{week_folder}")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # -----------------------------
    # Load CSVs (ONLY PATH CHANGED)
    # -----------------------------
    employee_df = pd.read_csv("data/raw/employee_list.csv")
    team_usage_df = pd.read_csv(RAW_DIR / "usage.csv")
    cursor_df = pd.read_csv(RAW_DIR / "leaderboard.csv")

    # -----------------------------
    # Normalize email columns
    # -----------------------------
    employee_df["Email"] = employee_df["Email"].str.lower().str.strip()
    team_usage_df["User"] = team_usage_df["User"].str.lower().str.strip()
    cursor_df["Email"] = cursor_df["Email"].str.lower().str.strip()

    # -----------------------------
    # Drop Date column
    # -----------------------------
    if "Date" in cursor_df.columns:
        cursor_df = cursor_df.drop(columns=["Date"])

    if "Name" in cursor_df.columns:
        cursor_df = cursor_df.drop(columns=["Name"])

    if "Name" in team_usage_df.columns:
        team_usage_df = team_usage_df.drop(columns=["Name"])

    # -----------------------------
    # Rename for join
    # -----------------------------
    team_usage_df = team_usage_df.rename(columns={"User": "Email"})

    # -----------------------------
    # Preserve column order
    # -----------------------------
    employee_cols = list(employee_df.columns)
    cursor_cols = [c for c in cursor_df.columns if c != "Email"]
    team_cols = [c for c in team_usage_df.columns if c != "Email"]

    # -----------------------------
    # Merge datasets
    # -----------------------------
    merged_df = (
        employee_df
        .merge(cursor_df, on="Email", how="left")
        .merge(team_usage_df, on="Email", how="left")
    )

    # -----------------------------
    # Reorder columns
    # -----------------------------
    final_columns = employee_cols + cursor_cols + team_cols
    final_df = merged_df.loc[:, final_columns]

    # -----------------------------
    # SAVE (ONLY CHANGE HERE)
    # -----------------------------
    output_file = PROCESSED_DIR / "merged.csv"
    final_df.to_csv(output_file, index=False)

    print("✅ Data merged successfully")
    print(f"Saved at: {output_file}")
    print(f"Final columns count: {len(final_columns)}")

    return output_file


if __name__ == "__main__":
    run_merge()
