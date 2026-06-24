import os
import tempfile

# logs de teste vão para um diretório temporário (não poluem backend/logs/)
os.environ.setdefault("POKER_LOG_DIR", tempfile.mkdtemp(prefix="poker_test_logs_"))
