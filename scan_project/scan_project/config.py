from os.path import join

import environ
from django.conf import settings

env = environ.Env()
environ.Env.read_env(join(settings.BASE_DIR, ".env"))
INPUT_DIR = env("INPUT_DIR", default=join(settings.BASE_DIR, "input_dir"))
ERROR_DIR = env("ERROR_DIR", default=join(settings.BASE_DIR, "error_dir"))
OUTPUT_DIR = env("OUTPUT_DIR", default=join(settings.BASE_DIR, "output_dir"))
OLLAMA_HOST = env("OLLAMA_HOST", default="http://10.0.0.3:30068")
OLLAMA_MODEL = env("OLLAMA_MODEL", default="gemma4")
