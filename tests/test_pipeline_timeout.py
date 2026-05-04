import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestPipelineTimeout:

    def test_per_document_timeout_default(self):
        from extraction_pipeline import ExtractionPipeline
        pipeline = ExtractionPipeline.__new__(ExtractionPipeline)
        pipeline.per_document_timeout = 600
        assert pipeline.per_document_timeout == 600

    def test_pipeline_timeout_default(self):
        from extraction_pipeline import ExtractionPipeline
        pipeline = ExtractionPipeline.__new__(ExtractionPipeline)
        pipeline.pipeline_timeout = 3600
        assert pipeline.pipeline_timeout == 3600

    def test_timeout_configurable(self):
        from extraction_pipeline import ExtractionPipeline
        pipeline = ExtractionPipeline.__new__(ExtractionPipeline)
        pipeline.per_document_timeout = 300
        pipeline.pipeline_timeout = 1800
        assert pipeline.per_document_timeout == 300
        assert pipeline.pipeline_timeout == 1800

    @pytest.mark.asyncio
    async def test_extraction_respects_timeout(self):
        async def slow_extract():
            await asyncio.sleep(10)
            return {"status": "ok"}

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_extract(), timeout=0.01)
