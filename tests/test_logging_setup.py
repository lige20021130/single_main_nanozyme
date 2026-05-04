import logging
import tempfile
from pathlib import Path
import pytest
import logging_setup


@pytest.fixture(autouse=True)
def reset_logging():
    logging_setup._configured = False
    root = logging.getLogger()
    for h in list(root.handlers):
        h.close()
    root.handlers.clear()
    root.setLevel(logging.WARNING)
    yield
    logging_setup._configured = False
    root = logging.getLogger()
    for h in list(root.handlers):
        h.close()
    root.handlers.clear()


class TestLoggingSetup:

    def test_setup_logging_creates_handlers(self):
        root = logging.getLogger()
        initial_count = len(root.handlers)
        logging_setup.setup_logging(level=logging.DEBUG)
        assert len(root.handlers) >= 1

    def test_setup_logging_with_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = str(Path(tmpdir) / "test.log")
            logging_setup.setup_logging(level=logging.INFO, log_file=log_file)
            logger = logging_setup.get_logger("test_module")
            logger.info("test message")
            for h in list(logging.getLogger().handlers):
                h.close()
            assert Path(log_file).exists()
            content = Path(log_file).read_text(encoding="utf-8")
            assert "test message" in content

    def test_get_logger_returns_logger(self):
        logger = logging_setup.get_logger("test_get_logger")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_get_logger"

    def test_module_log_levels_applied(self):
        logging_setup.setup_logging(level=logging.DEBUG)
        api_logger = logging.getLogger("api_client")
        assert api_logger.level == logging.INFO
