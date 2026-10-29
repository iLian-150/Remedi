"""Verify the native environment loader using synthetic configuration only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name == "posix", "the production loader requires Bash")
class NativeEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / "fixture.env"

    def load(self, content=None):
        if content is not None:
            self.config.write_text(content, encoding="utf-8")
        loader = Path(__file__).with_name("load_backend_model_env.sh")
        inspect = (
            "import json,os; print(json.dumps({k:v for k,v in os.environ.items() "
            "if k.startswith(('LLM_', 'DASHSCOPE_', 'RAG_')) or k in ('DATABASE_URL','UPLOAD_DIR')}))"
        )
        environment = {
            "PATH": str(Path(sys.executable).parent) + os.pathsep + "/usr/bin:/bin",
            "REMEDI_MODEL_ENV_FILE": str(self.config),
            "DATABASE_URL": "preserved-database",
            "LLM_TIMEOUT_SECONDS": "17",
        }
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; python -c "$2"', "check", str(loader), inspect],
            env=environment, text=True, capture_output=True, check=True,
        )
        return json.loads(result.stdout), result.stderr

    def test_models_rag_and_database_isolation(self):
        values, _ = self.load(
            'DASHSCOPE_API_KEY="synthetic $; # value"\n'
            "DASHSCOPE_MODEL=kimi-k3\nDASHSCOPE_VISION_MODEL=kimi-k3\n"
            "RAG_MILVUS_URI=http://milvus:19530/\nRAG_EMBEDDING_DIMENSIONS=1024\n"
            "RAG_RERANK_MODEL=''\nDATABASE_URL=must-not-load\nUPLOAD_DIR=must-not-load\n"
        )
        self.assertEqual(values["DASHSCOPE_API_KEY"], "synthetic $; # value")
        self.assertEqual(values["RAG_MILVUS_URI"], "http://127.0.0.1:19530")
        self.assertEqual(values["RAG_EMBEDDING_DIMENSIONS"], "1024")
        self.assertEqual(values["RAG_RERANK_MODEL"], "")
        self.assertEqual(values["DATABASE_URL"], "preserved-database")
        self.assertNotIn("UPLOAD_DIR", values)

    def test_custom_remote_endpoint_is_preserved(self):
        values, _ = self.load("RAG_MILVUS_URI=https://remote.example.invalid:19530\n")
        self.assertEqual(values["RAG_MILVUS_URI"], "https://remote.example.invalid:19530")

    def test_missing_configuration_keeps_startup_available(self):
        values, warning = self.load()
        self.assertEqual(values, {"DATABASE_URL": "preserved-database", "LLM_TIMEOUT_SECONDS": "17"})
        self.assertIn("FileNotFoundError", warning)
        self.assertNotIn(str(self.config), warning)

    def test_incomplete_credentials_keep_startup_available(self):
        values, _ = self.load("DASHSCOPE_MODEL=kimi-k3\n")
        self.assertEqual(values["DASHSCOPE_MODEL"], "kimi-k3")

    def test_values_cannot_execute_shell_commands(self):
        marker = self.root / "must-not-exist"
        value = f"$(touch {marker})"
        values, _ = self.load(f"DASHSCOPE_API_KEY='{value}'\n")
        self.assertEqual(values["DASHSCOPE_API_KEY"], value)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
