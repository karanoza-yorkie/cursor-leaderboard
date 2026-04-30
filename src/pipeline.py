import logging
from downloader import run_download
from merge_data import run_merge
from analysis import run_analysis
from generate_leaderboard import main as generate
from utils import ensure_dirs

ensure_dirs()

logging.basicConfig(
    filename="logs/pipeline.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def run_pipeline():
    logging.info("🚀 START PIPELINE")

    try:
        logging.info("Step 1: Downloading reports")
        run_download()

        logging.info("Step 2: Merging data")
        run_merge()

        logging.info("Step 3: Running analysis")
        run_analysis()

        logging.info("Step 4: Generating leaderboard")
        generate()

        logging.info("✅ PIPELINE SUCCESS")

    except Exception as e:
        logging.exception(f"❌ PIPELINE FAILED: {e}")
        raise

if __name__ == "__main__":
    run_pipeline()
