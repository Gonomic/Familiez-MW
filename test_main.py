import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from fastapi.testclient import TestClient

from main import app, format_result


# Create test client
client = TestClient(app)


# ==================== Tests for format_result function ====================

class TestFormatResult:
    """Test suite for the format_result utility function."""

    def test_format_result_empty_list(self):
        """Test format_result returns correct structure for empty results."""
        result = format_result([])
        assert result == [{"numberOfRecords": 0}]
        assert len(result) == 1

    def test_format_result_single_record(self):
        """Test format_result with a single database record."""
        # Mock a database row object
        mock_row = Mock()
        mock_row._asdict.return_value = {"id": 1, "name": "John"}
        
        result = format_result([mock_row])
        
        assert len(result) == 2
        assert result[0] == {"numberOfRecords": 1}
        assert result[1] == {"id": 1, "name": "John"}

    def test_format_result_multiple_records(self):
        """Test format_result with multiple database records."""
        mock_row1 = Mock()
        mock_row1._asdict.return_value = {"id": 1, "name": "John"}
        
        mock_row2 = Mock()
        mock_row2._asdict.return_value = {"id": 2, "name": "Jane"}
        
        mock_row3 = Mock()
        mock_row3._asdict.return_value = {"id": 3, "name": "Bob"}
        
        result = format_result([mock_row1, mock_row2, mock_row3])
        
        assert len(result) == 4
        assert result[0] == {"numberOfRecords": 3}
        assert result[1] == {"id": 1, "name": "John"}
        assert result[2] == {"id": 2, "name": "Jane"}
        assert result[3] == {"id": 3, "name": "Bob"}


# ==================== Tests for API Endpoints ====================

class TestRootEndpoint:
    """Test suite for the root endpoint."""

    def test_read_root(self):
        """Test root endpoint returns correct welcome message."""
        response = client.get("/")
        
        assert response.status_code == 200
        assert "Hello visitor" in response.json()
        assert response.json()["Hello visitor"] == "The Familiez Fastapi api lives!"


class TestPingAPIEndpoint:
    """Test suite for the ping API endpoint."""

    def test_ping_api_with_valid_timestamp(self):
        """Test ping API endpoint returns both frontend and middleware timestamps."""
        test_time = datetime.now().isoformat()
        
        response = client.get(f"/pingAPI?timestampFE={test_time}")
        
        assert response.status_code == 200
        result = response.json()
        assert len(result) == 1
        assert "FE request time" in result[0]
        assert "MW request time" in result[0]

    def test_ping_api_missing_timestamp(self):
        """Test ping API endpoint without timestamp parameter."""
        response = client.get("/pingAPI")
        
        # Should fail validation
        assert response.status_code == 422  # Unprocessable Entity


class TestPingDBEndpoint:
    """Test suite for the ping database endpoint."""

    @patch('main.engine')
    def test_ping_db_success(self, mock_engine):
        """Test successful database ping."""
        # Setup mock
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        
        mock_result = Mock()
        mock_result._asdict.return_value = {
            "datetimeFErequest": datetime.now(),
            "timestampMWrequest": datetime.now()
        }
        
        mock_results_proxy = Mock()
        mock_results_proxy.fetchall.return_value = [mock_result]
        mock_connection.execute.return_value = mock_results_proxy
        
        test_time = datetime.now().isoformat()
        response = client.get(f"/pingDB?timestampFE={test_time}")
        
        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, list)
        assert len(result) > 0

    @patch('main.engine')
    def test_ping_db_connection_error(self, mock_engine):
        """Test database ping with connection error."""
        # Setup mock to raise exception
        mock_engine.connect.return_value.__enter__.side_effect = Exception("Connection failed")
        
        test_time = datetime.now().isoformat()
        response = client.get(f"/pingDB?timestampFE={test_time}")
        
        assert response.status_code == 500
        assert "Database connection failed" in response.json()["detail"]


class TestGetPersonsLikeEndpoint:
    """Test suite for the GetPersonsLike endpoint."""

    @patch('main.engine')
    def test_get_persons_like_with_results(self, mock_engine):
        """Test GetPersonsLike returns formatted results."""
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        
        mock_row = Mock()
        mock_row._asdict.return_value = {"id": 1, "firstName": "John", "lastName": "Doe"}
        
        mock_results_proxy = Mock()
        mock_results_proxy.fetchall.return_value = [mock_row]
        mock_connection.execute.return_value = mock_results_proxy
        
        response = client.get("/GetPersonsLike?stringToSearchFor=John")
        
        assert response.status_code == 200
        result = response.json()
        assert result[0]["numberOfRecords"] == 1
        assert result[1]["firstName"] == "John"

    @patch('main.engine')
    def test_get_persons_like_no_results(self, mock_engine):
        """Test GetPersonsLike with no matching results."""
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        
        mock_results_proxy = Mock()
        mock_results_proxy.fetchall.return_value = []
        mock_connection.execute.return_value = mock_results_proxy
        
        response = client.get("/GetPersonsLike?stringToSearchFor=NonExistent")
        
        assert response.status_code == 200
        result = response.json()
        assert result[0]["numberOfRecords"] == 0

    def test_get_persons_like_missing_parameter(self):
        """Test GetPersonsLike without required parameter."""
        response = client.get("/GetPersonsLike")
        
        assert response.status_code == 422  # Unprocessable Entity

    @patch('main.engine')
    def test_get_persons_like_query_error(self, mock_engine):
        """Test GetPersonsLike with database query error."""
        mock_engine.connect.return_value.__enter__.side_effect = Exception("Query error")
        
        response = client.get("/GetPersonsLike?stringToSearchFor=test")
        
        assert response.status_code == 500
        assert "Query failed" in response.json()["detail"]


class TestGetSiblingsEndpoint:
    """Test suite for the GetSiblings endpoint."""

    @patch('main.engine')
    def test_get_siblings_with_results(self, mock_engine):
        """Test GetSiblings returns formatted results."""
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        
        mock_row1 = Mock()
        mock_row1._asdict.return_value = {"id": 2, "name": "Jane"}
        
        mock_row2 = Mock()
        mock_row2._asdict.return_value = {"id": 3, "name": "Bob"}
        
        mock_results_proxy = Mock()
        mock_results_proxy.fetchall.return_value = [mock_row1, mock_row2]
        mock_connection.execute.return_value = mock_results_proxy
        
        response = client.get("/GetSiblings?parentID=1")
        
        assert response.status_code == 200
        result = response.json()
        assert result[0]["numberOfRecords"] == 2
        assert len(result) == 3  # numberOfRecords + 2 rows

    @patch('main.engine')
    def test_get_siblings_no_results(self, mock_engine):
        """Test GetSiblings with no siblings found."""
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        
        mock_results_proxy = Mock()
        mock_results_proxy.fetchall.return_value = []
        mock_connection.execute.return_value = mock_results_proxy
        
        response = client.get("/GetSiblings?parentID=999")
        
        assert response.status_code == 200
        result = response.json()
        assert result[0]["numberOfRecords"] == 0

    def test_get_siblings_missing_parameter(self):
        """Test GetSiblings without required parameter."""
        response = client.get("/GetSiblings")
        
        assert response.status_code == 422

    def test_get_siblings_invalid_parameter(self):
        """Test GetSiblings with invalid parentID parameter."""
        response = client.get("/GetSiblings?parentID=invalid")
        
        assert response.status_code == 422

    @patch('main.engine')
    def test_get_siblings_database_error(self, mock_engine):
        """Test GetSiblings with database error."""
        mock_engine.connect.return_value.__enter__.side_effect = Exception("DB error")
        
        response = client.get("/GetSiblings?parentID=1")
        
        assert response.status_code == 500
        assert "Query failed" in response.json()["detail"]


class TestGetFatherEndpoint:
    """Test suite for the GetFather endpoint."""

    @patch('main.engine')
    def test_get_father_with_result(self, mock_engine):
        """Test GetFather returns father information."""
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        
        mock_row = Mock()
        mock_row._asdict.return_value = {"id": 1, "name": "John Sr", "birthDate": "1950-01-01"}
        
        mock_results_proxy = Mock()
        mock_results_proxy.fetchall.return_value = [mock_row]
        mock_connection.execute.return_value = mock_results_proxy
        
        response = client.get("/GetFather?childID=5")
        
        assert response.status_code == 200
        result = response.json()
        assert result[0]["numberOfRecords"] == 1
        assert result[1]["name"] == "John Sr"

    @patch('main.engine')
    def test_get_father_not_found(self, mock_engine):
        """Test GetFather when father doesn't exist."""
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        
        mock_results_proxy = Mock()
        mock_results_proxy.fetchall.return_value = []
        mock_connection.execute.return_value = mock_results_proxy
        
        response = client.get("/GetFather?childID=999")
        
        assert response.status_code == 200
        result = response.json()
        assert result[0]["numberOfRecords"] == 0

    def test_get_father_missing_parameter(self):
        """Test GetFather without required parameter."""
        response = client.get("/GetFather")
        
        assert response.status_code == 422

    def test_get_father_invalid_parameter(self):
        """Test GetFather with invalid childID parameter."""
        response = client.get("/GetFather?childID=notanumber")
        
        assert response.status_code == 422

    @patch('main.engine')
    def test_get_father_database_error(self, mock_engine):
        """Test GetFather with database error."""
        mock_engine.connect.return_value.__enter__.side_effect = Exception("DB connection lost")
        
        response = client.get("/GetFather?childID=1")
        
        assert response.status_code == 500
        assert "Query failed" in response.json()["detail"]
