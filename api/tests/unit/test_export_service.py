"""
Unit tests for export service.

Tests:
- start_export() returns job_id
- get_export_status() returns correct status
- cancel_export() works
- Expired jobs are cleaned up
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime, timedelta
from app.services.export_service import (
    ExportService,
    get_export_service,
    set_export_service
)
from app.infrastructure.queue import (
    InMemoryQueue,
    Job,
    JobStatus
)


class TestExportService:
    """Tests for ExportService class."""
    
    @pytest.fixture
    def mock_queue(self):
        """Create a mock job queue."""
        queue = Mock(spec=InMemoryQueue)
        queue.enqueue = Mock(return_value=True)
        queue.get_job = Mock(return_value=None)
        queue.update_status = Mock(return_value=True)
        queue.cancel = Mock(return_value=True)
        queue.list_jobs = Mock(return_value=[])
        queue.cleanup = Mock(return_value=0)
        return queue
    
    @pytest.fixture
    def mock_exporter(self):
        """Create a mock DiscordExporter."""
        exporter = Mock()
        exporter.export_channel = Mock(return_value={
            "status": "success",
            "message_count": 100,
            "exported_files": ["file1.json", "file2.jsonl"]
        })
        return exporter
    
    @pytest.fixture
    def export_service(self, mock_queue):
        """Create ExportService with mock queue."""
        with patch('app.services.export_service.DiscordExporter') as mock_exporter_class:
            mock_exporter_class.return_value = Mock(
                export_channel=Mock(return_value={
                    "status": "success",
                    "message_count": 100,
                    "exported_files": []
                })
            )
            service = ExportService(queue=mock_queue)
            return service
    
    def test_start_export_returns_job_id(self, mock_queue):
        """Test that start_export returns a valid job ID."""
        with patch('app.services.export_service.DiscordExporter'):
            service = ExportService(queue=mock_queue)
            
            job_id = service.start_export({
                "token": "test-token",
                "channel_id": "123456",
                "output_dir": "exports"
            })
            
            assert job_id is not None
            assert isinstance(job_id, str)
            # UUID format
            assert len(job_id) == 36
    
    def test_start_export_enqueues_job(self, mock_queue):
        """Test that start_export adds job to queue."""
        with patch('app.services.export_service.DiscordExporter'):
            service = ExportService(queue=mock_queue)
            
            service.start_export({
                "token": "test-token",
                "channel_id": "123456"
            })
            
            mock_queue.enqueue.assert_called_once()
    
    def test_get_export_status_returns_status(self, export_service, mock_queue):
        """Test that get_export_status returns job status."""
        # Setup mock to return a job
        mock_job = Job(
            id="test-job-id",
            status=JobStatus.PROCESSING,
            data={"channel_id": "123456"},
            progress=50,
            progress_message="Processing..."
        )
        mock_queue.get_job.return_value = mock_job
        
        status = export_service.get_export_status("test-job-id")
        
        assert status is not None
        assert status["job_id"] == "test-job-id"
        assert status["status"] == "processing"
        assert status["progress"] == 50
        assert status["progress_message"] == "Processing..."
    
    def test_get_export_status_returns_none_for_missing(self, export_service, mock_queue):
        """Test that get_export_status returns None for missing job."""
        mock_queue.get_job.return_value = None
        
        status = export_service.get_export_status("non-existent-id")
        
        assert status is None
    
    def test_cancel_export_returns_true(self, export_service, mock_queue):
        """Test that cancel_export returns True on success."""
        mock_queue.cancel.return_value = True
        
        result = export_service.cancel_export("test-job-id")
        
        assert result is True
        mock_queue.cancel.assert_called_once_with("test-job-id")
    
    def test_cancel_export_returns_false_for_missing(self, export_service, mock_queue):
        """Test that cancel_export returns False for missing job."""
        mock_queue.cancel.return_value = False
        
        result = export_service.cancel_export("non-existent-id")
        
        assert result is False
    
    def test_cancel_running_task(self, export_service, mock_queue):
        """Test that running task is cancelled when job is cancelled."""
        # Create a mock running task
        mock_task = Mock(done=Mock(return_value=False), cancel=Mock(return_value=True))
        export_service._running_tasks["test-job-id"] = mock_task
        
        export_service.cancel_export("test-job-id")
        
        mock_task.cancel.assert_called_once()
        assert "test-job-id" not in export_service._running_tasks
    
    def test_list_exports_returns_job_list(self, export_service, mock_queue):
        """Test that list_exports returns list of jobs."""
        mock_jobs = [
            Job(id="job1", status=JobStatus.COMPLETED, data={}, progress=100),
            Job(id="job2", status=JobStatus.PROCESSING, data={}, progress=50),
        ]
        mock_queue.list_jobs.return_value = mock_jobs
        
        exports = export_service.list_exports()
        
        assert len(exports) == 2
        assert exports[0]["job_id"] == "job1"
        assert exports[0]["status"] == "completed"
    
    def test_list_exports_filters_by_status(self, export_service, mock_queue):
        """Test that list_exports filters by status."""
        export_service.list_exports(status="completed")
        
        mock_queue.list_jobs.assert_called_once()
        call_args = mock_queue.list_jobs.call_args
        assert call_args[1]["status"] == JobStatus.COMPLETED
    
    def test_cleanup_removes_expired_jobs(self, export_service, mock_queue):
        """Test that cleanup removes expired jobs."""
        mock_queue.cleanup.return_value = 5
        
        result = export_service.cleanup()
        
        assert result == 5
        mock_queue.cleanup.assert_called_once()
    
    def test_get_export_status_includes_timestamps(self, export_service, mock_queue):
        """Test that get_export_status includes timestamps."""
        now = datetime.utcnow()
        mock_job = Job(
            id="test-job",
            status=JobStatus.PENDING,
            data={},
            created_at=now,
            updated_at=now
        )
        mock_queue.get_job.return_value = mock_job
        
        status = export_service.get_export_status("test-job")
        
        assert "created_at" in status
        assert "updated_at" in status
    
    def test_get_export_status_includes_result(self, export_service, mock_queue):
        """Test that get_export_status includes result when completed."""
        mock_job = Job(
            id="test-job",
            status=JobStatus.COMPLETED,
            data={},
            result={"message_count": 100, "exported_files": ["file.json"]},
            progress=100
        )
        mock_queue.get_job.return_value = mock_job
        
        status = export_service.get_export_status("test-job")
        
        assert status["result"] is not None
        assert status["result"]["message_count"] == 100
    
    def test_get_export_status_includes_error(self, export_service, mock_queue):
        """Test that get_export_status includes error when failed."""
        mock_job = Job(
            id="test-job",
            status=JobStatus.FAILED,
            data={},
            error="Export failed: Network error",
            progress=100
        )
        mock_queue.get_job.return_value = mock_job
        
        status = export_service.get_export_status("test-job")
        
        assert status["error"] is not None
        assert "Network error" in status["error"]


class TestExportServiceIntegration:
    """Integration tests for ExportService with real InMemoryQueue."""
    
    def test_start_export_creates_pending_job(self):
        """Test that start_export creates a pending job."""
        queue = InMemoryQueue()
        service = ExportService(queue=queue)
        
        job_id = service.start_export({
            "token": "test-token",
            "channel_id": "123456"
        })
        
        status = service.get_export_status(job_id)
        
        assert status is not None
        assert status["status"] == "pending"
    
    def test_export_service_uses_default_queue(self):
        """Test that ExportService uses InMemoryQueue by default."""
        service = ExportService()
        
        assert service.queue is not None
        assert isinstance(service.queue, InMemoryQueue)
    
    def test_multiple_jobs_have_unique_ids(self):
        """Test that multiple jobs get unique IDs."""
        queue = InMemoryQueue()
        service = ExportService(queue=queue)
        
        job_id_1 = service.start_export({"channel_id": "1"})
        job_id_2 = service.start_export({"channel_id": "2"})
        
        assert job_id_1 != job_id_2
    
    def test_cancel_pending_job(self):
        """Test cancelling a pending job."""
        queue = InMemoryQueue()
        service = ExportService(queue=queue)
        
        job_id = service.start_export({"channel_id": "123"})
        
        # Cancel the job
        result = service.cancel_export(job_id)
        
        assert result is True
        
        status = service.get_export_status(job_id)
        assert status["status"] == "cancelled"


class TestGetExportService:
    """Tests for get_export_service and set_export_service functions."""
    
    def test_get_export_service_returns_singleton(self):
        """Test that get_export_service returns singleton."""
        # Reset the global instance
        import app.services.export_service as es_module
        es_module._export_service = None
        
        service1 = get_export_service()
        service2 = get_export_service()
        
        assert service1 is service2
    
    def test_set_export_service_allows_override(self):
        """Test that set_export_service allows dependency injection."""
        # Reset
        import app.services.export_service as es_module
        es_module._export_service = None
        
        custom_service = ExportService(queue=InMemoryQueue())
        set_export_service(custom_service)
        
        result = get_export_service()
        
        assert result is custom_service
        
        # Reset again for other tests
        es_module._export_service = None
