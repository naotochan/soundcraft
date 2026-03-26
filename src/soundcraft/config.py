import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")

MODELS = ["melody-large", "stereo-melody-large", "large", "stereo-large"]

DEFAULT_MODEL = "melody-large"
DEFAULT_DURATION = 30
DEFAULT_OUTPUT_DIR = Path("output")

REPLICATE_MODEL_VERSION = "671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"

LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "liquid/lfm2-24b-a2b")
