"""
Integration tests for export job flow.

Tests:
- Async export creates job
- Job status transitions (pending -> processing -> completed)
- Job can be cancelled
"""
import pytest
import os
import asyncio
from unittest.mock import patch, Mock, AsyncMock
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

# Enable async export for these tests
os.environ["ASYNC_EXPORT_ENABLED"] = "true"

from app.main import app
from app.services.export_service import ExportService, set_export_service
from app.infrastructure.queue import InMemoryQueue, Job, JobStatus


@pytest.fixture
def client():
    """Create a test client."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def export_service():
    """Create a fresh export service with in-memory queue."""
    queue = InMemoryQueue()
    service = ExportService(queue=queue)
    set_export_service(service)
    yield service
    # Reset global service
    set_export_service(None)


@pytest.fixture
def mock_exporter():
    """Mock DiscordExporter for testing."""
    with patch('app.services.export_service.DiscordExporter') as mock:
        mock_instance = Mock()
        mock_instance.export_channel = Mock(return_value={
            "status": "success",
            "message_count": 100,
            "exported_files": ["exports/test.json"]
        })
        mock.return_value = mock_instance
        yield mock


class TestAsyncExport:
    """Tests for async export flow."""
    
    def test_async_export_creates_job(self, client, export_service, mock_exporter):
        """Test that async export creates a job."""
        response = client.post("/api/v1/export", json={
            "token": "test-token",
            "channel_id": "123456789"
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return job_id
        assert "job_id" in data
        assert data["status"] == "accepted"
        
        # Job should exist in queue
        job_status = export_service.get_export_status(data["job_id"])
        assert job_status is not None
        assert job_status["status"] == "pending"
    
    def test_job_status_pending(self, client, export_service, mock_exporter):
        """Test that job starts in pending state."""
        response = client.post("/api/v1/export", json={
            "token": "test-token",
            "channel_id": "123456789"
        })
        
        job_id = response.json()["job_id"]
        
        status = export_service.get_export_status(job_id)
        
        assert status["status"] == "pending"
    
    def test_get_job_status(self, client, export_service):
        """Test getting job status via API."""
        # Create a job directly in the queue
        job_id = export_service.start_export({
            "token": "test-token",
            "channel_id": "123456789"
        })
        
        # Get status via API
        response = client.get(f"/api/v1/jobs/{job_id}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["job_id"] == job_id
        assert data["status"] in ["pending", "processing"]
    
    def test_get_job_status_not_found(self, client):
        """Test that 404 is returned for non-existent job."""
        response = client.get("/api/v1/jobs/fake-job-id")
        
        assert response.status_code == 404
    
    def test_cancel_job_via_api(self, client, export_service):
        """Test cancelling job via API."""
        # Create a job
        job_id = export_service.start_export({
            "token": "test-token",
            "channel_id": "123456789"
        })
        
        # Cancel via API
        response = client.delete(f"/api/v1/jobs/{job_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"
        
        # Verify job is cancelled
        status = export_service.get_export_status(job_id)
        assert status["status"] == "cancelled"
    
    def test_cancel_job_not_found(self, client):
        """Test cancelling non-existent job returns 404."""
        response = client.delete("/api/v1/jobs/fake-job-id")
        
        assert response.status_code == 404
    
    def test_cancel_completed_job_fails(self, client, export_service):
        """Test that cancelling completed job fails."""
        # Create and complete a job
        job_id = export_service.start_export({
            "token": "test-token",
            "channel_id": "123456789"
        })
        
        # Manually set to completed
        export_service.queue.update_status(
            job_id,
            JobStatus.COMPLETED,
            result={"message_count": 100}
        )
        
        # Try to cancel
        response = client.delete(f"/api/v1/jobs/{job_id}")
        
        # Should still return 200 but job remains completed
        # (or could be 404 depending on implementation)
        status = export_service.get_export_status(job_id)
        assert status["status"] == "completed"


class TestJobStatusTransitions:
    """Tests for job status transitions."""
    
    def test_job_status_transitions(self, export_service, mock_exporter):
        """Test job goes through status transitions."""
        # Start export
        job_id = export_service.start_export({
            "token": "test-token",
            "channel_id": "123456789"
        })
        
        # Check pending
        status = export_service.get_export_status(job_id)
        assert status["status"] == "pending"
        
        # Note: In real async flow, status would transition to processing
        # then completed. In tests with mocks, we can manually update.
        
        # Simulate processing
        export_service.queue.update_status(
            job_id,
            JobStatus.PROCESSING,
            progress=50,
            progress_message="Processing messages..."
        )
        
        status = export_service.get_export_status(job_id)
        assert status["status"] == "processing"
        assert status["progress"] == 50
        
        # Simulate completion
        export_service.queue.update_status(
            job_id,
            JobStatus.COMPLETED,
            result={
                "status": "success",
                "message_count": 100,
                "exported_files": ["test.json"]
            },
            progress=100,
            progress_message="Export completed"
        )
        
        status = export_service.get_export_status(job_id)
        assert status["status"] == "completed"
        assert status["result"] is not None
        assert status["result"]["message_count"] == 100
    
    def test_job_failure_transition(self, export_service):
        """Test job transitions to failed state."""
        job_id = export_service.start_export({
            "token": "test-token",
            "channel_id": "123456789"
        })
        
        # Simulate failure
        export_service.queue.update_status(
            job_id,
            JobStatus.FAILED,
            error="Network error: Connection timeout",
            progress=100,
            progress_message="Export failed"
        )
        
        status = export_service.get_export_status(job_id)
        
        assert status["status"] == "failed"
        assert status["error"] is not None
        assert "Network error" in status["error"]


class TestJobList:
    """Tests for listing jobs."""
    
    def test_list_all_jobs(self, export_service):
        """Test listing all jobs."""
        # Create multiple jobs
        job1_id = export_service.start_export({"channel_id": "1"})
        job2_id = export_service.start_export({"channel_id": "2"})
        
        jobs = export_service.list_exports()
        
        assert len(jobs) >= 2
        job_ids = [j["job_id"] for j in jobs]
        assert job1_id in job_ids
        assert job2_id in job_ids
    
    def test_list_jobs_by_status(self, export_service):
        """Test filtering jobs by status."""
        # Create jobs with different statuses
        job1_id = export_service.start_export({"channel_id": "1"})
        job2_id = export_service.start_export({"channel_id": "2"})
        
        # Set different statuses
        export_service.queue.update_status(job1_id, JobStatus.COMPLETED)
        
        # Filter by status
        completed = export_service.list_exports(status="completed")
        pending = export_service.list_exports(status="pending")
        
        assert any(j["job_id"] == job1_id for j in completed)
        assert any(j["job_id"] == job2_id for j in pending)
    
    def test_list_jobs_with_limit(self, export_service):
        """Test limiting job list."""
        # Create many jobs
        for i in range(5):
            export_service.start_export({"channel_id": str(i)})
        
        jobs = export_service.list_exports(limit=3)
        
        assert len(jobs) <= 3


class TestJobCleanup:
    """Tests for job cleanup."""
    
    def test_cleanup_removes_old_jobs(self, export_service):
        """Test cleanup removes expired jobs."""
        # Create and complete a job
        job_id = export_service.start_export({"channel_id": "1"})
        export_service.queue.update_status(
            job_id,
            JobStatus.COMPLETED,
            result={"message_count": 100}
        )
        
        # Manually set old timestamp
        job = export_service.queue.get_job(job_id)
        job.updated_at = datetime.utcnow() - timedelta(hours=25)
        
        # Run cleanup
        removed = export_service.cleanup()
        
        assert removed >= 1
        
        # Job should be gone
        status = export_service.get_export_status(job_id)
        assert status is None
    
    def test_cleanup_keeps_recent_jobs(self, export_service):
        """Test cleanup keeps recent jobs."""
        # Create and complete a job
        job_id = export_service.start_export({"channel_id": "1"})
        export_service.queue.update_status(
            job_id,
            JobStatus.COMPLETED,
            result={"message_count": 100}
        )
        
        # Run cleanup
        removed = export_service.cleanup()
        
        # Job should still exist
        status = export_service.get_export_status(job_id)
        assert status is not None


class TestConcurrentJobs:
    """Tests for handling concurrent jobs."""
    
    def test_multiple_concurrent_jobs(self, export_service):
        """Test creating multiple jobs concurrently."""
        job_ids = []
        
        for i in range(3):
            job_id = export_service.start_export({
                "token": "test-token",
                "channel_id": str(i)
            })
            job_ids.append(job_id)
        
        # All should have unique IDs
        assert len(set(job_ids)) == 3
        
        # All should exist
        for job_id in job_ids:
            status = export_service.get_export_status(job_id)
            assert status is not None
    
    def test_list_includes_all_statuses(self, export_service):
        """Test that list includes jobs in all statuses."""
        # Create jobs with different statuses
        job1_id = export_service.start_export({"channel_id": "1"})
        job2_id = export_service.start_export({"channel_id": "2"})
        job3_id = export_service.start_export({"channel_id": "3"})
        
        export_service.queue.update_status(job2_id, JobStatus.COMPLETED)
        export_service.queue.update_status(job3_id, JobStatus.FAILED, error="Test error")
        
        jobs = export_service.list_exports()
        
        statuses = {j["job_id"]: j["status"] for j in jobs}
        
        assert statuses[job1_id] == "pending"
        assert statuses[job2_id] == "completed"
        assert statuses[job3_id] == "failed"
