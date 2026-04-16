import pytest
from unittest.mock import Mock, MagicMock, patch
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


@pytest.fixture
def admin_session():
    with patch(
        "main.validate_session",
        return_value={
            "username": "tester",
            "role": "admin",
            "is_admin": True,
            "is_user": True,
            "groups": ["admins"],
        },
    ):
        yield


class TestMarriageEndpoints:
    @patch("main.engine")
    def test_get_marriage_history_for_person_empty_result(self, mock_engine, admin_session):
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        mock_proxy = Mock()
        mock_proxy.fetchall.return_value = []
        mock_connection.execute.return_value = mock_proxy

        response = client.get("/marriages/history/999999", cookies={"familiez_session": "ok"})

        assert response.status_code == 200
        assert response.json() == [{"numberOfRecords": 0}]

    @patch("main.engine")
    def test_get_active_marriage_for_person(self, mock_engine, admin_session):
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        mock_row = Mock()
        mock_row._asdict.return_value = {
            "MarriageID": 12,
            "PartnerID": 22,
            "StartDate": "2020-01-01",
            "IsActive": 1,
        }
        mock_proxy = Mock()
        mock_proxy.fetchall.return_value = [mock_row]
        mock_connection.execute.return_value = mock_proxy

        response = client.get("/marriages/active/11", cookies={"familiez_session": "ok"})

        assert response.status_code == 200
        result = response.json()
        assert result[0]["numberOfRecords"] == 1
        assert result[1]["MarriageID"] == 12

    @patch("main.engine")
    def test_create_marriage_success(self, mock_engine, admin_session):
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        add_result_row = Mock()
        add_result_row._asdict.return_value = {
            "CompletedOk": 0,
            "Result": 0,
            "MarriageID": 99,
            "ErrorMessage": None,
        }
        add_result_proxy = Mock()
        add_result_proxy.fetchall.return_value = [add_result_row]
        mock_connection.execute.return_value = add_result_proxy

        response = client.post(
            "/marriages",
            json={"personAId": 11, "personBId": 22, "startDate": "2026-04-16"},
            cookies={"familiez_session": "ok"},
        )

        assert response.status_code == 200
        assert response.json() == {"success": True, "marriageId": 99}
        mock_connection.commit.assert_called_once()

    @patch("main.engine")
    def test_create_marriage_maps_conflict_from_sproc(self, mock_engine, admin_session):
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        add_result_row = Mock()
        add_result_row._asdict.return_value = {
            "CompletedOk": 1,
            "Result": 409,
            "MarriageID": None,
            "ErrorMessage": "Partner A heeft al een actieve partnerrelatie",
        }
        add_result_proxy = Mock()
        add_result_proxy.fetchall.return_value = [add_result_row]
        mock_connection.execute.return_value = add_result_proxy

        response = client.post(
            "/marriages",
            json={"personAId": 11, "personBId": 22, "startDate": "2026-04-16"},
            cookies={"familiez_session": "ok"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "Partner A heeft al een actieve partnerrelatie"
        mock_connection.rollback.assert_called_once()

    @patch("main.engine")
    def test_create_marriage_maps_not_found_from_sproc(self, mock_engine, admin_session):
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        add_result_row = Mock()
        add_result_row._asdict.return_value = {
            "CompletedOk": 1,
            "Result": 404,
            "MarriageID": None,
            "ErrorMessage": "Een of beide partners bestaan niet",
        }
        add_result_proxy = Mock()
        add_result_proxy.fetchall.return_value = [add_result_row]
        mock_connection.execute.return_value = add_result_proxy

        response = client.post(
            "/marriages",
            json={"personAId": 999998, "personBId": 999999, "startDate": "2026-04-16"},
            cookies={"familiez_session": "ok"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Een of beide partners bestaan niet"
        mock_connection.rollback.assert_called_once()

    def test_end_marriage_rejects_invalid_endreason(self, admin_session):
        response = client.put(
            "/marriages/1",
            json={
                "personAId": 11,
                "personBId": 22,
                "endDate": "2026-04-20",
                "endReason": "invalid_reason",
            },
            cookies={"familiez_session": "ok"},
        )

        assert response.status_code == 400
        assert "endReason" in response.json()["detail"]

    @patch("main.engine")
    def test_end_marriage_maps_unprocessable_from_sproc(self, mock_engine, admin_session):
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        active_row = Mock()
        active_row._asdict.return_value = {"MarriageID": 77}
        active_proxy = Mock()
        active_proxy.fetchall.return_value = [active_row]

        end_row = Mock()
        end_row._asdict.return_value = {
            "CompletedOk": 1,
            "Result": 422,
            "ErrorMessage": "Einddatum kan niet voor de startdatum liggen",
        }
        end_proxy = Mock()
        end_proxy.fetchall.return_value = [end_row]

        mock_connection.execute.side_effect = [active_proxy, end_proxy]

        response = client.put(
            "/marriages/77",
            json={
                "personAId": 11,
                "personBId": 22,
                "endDate": "2026-04-01",
                "endReason": "scheiding",
            },
            cookies={"familiez_session": "ok"},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "Einddatum kan niet voor de startdatum liggen"
        mock_connection.rollback.assert_called_once()

    @patch("main.engine")
    def test_end_marriage_requires_matching_marriage_id(self, mock_engine, admin_session):
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        active_row = Mock()
        active_row._asdict.return_value = {"MarriageID": 50}

        active_proxy = Mock()
        active_proxy.fetchall.return_value = [active_row]

        mock_connection.execute.side_effect = [active_proxy]

        response = client.put(
            "/marriages/99",
            json={
                "personAId": 11,
                "personBId": 22,
                "endDate": "2026-04-20",
                "endReason": "scheiding",
            },
            cookies={"familiez_session": "ok"},
        )

        assert response.status_code == 409
        assert "MarriageID" in response.json()["detail"]

    @patch("main.engine")
    def test_update_marriage_start_date_allows_partner_change_when_no_overlap(self, mock_engine, admin_session):
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        update_row = Mock()
        update_row._asdict.return_value = {
            "CompletedOk": 0,
            "Result": 0,
            "MarriageID": 77,
            "ErrorMessage": None,
        }
        update_proxy = Mock()
        update_proxy.fetchall.return_value = [update_row]

        mock_connection.execute.return_value = update_proxy

        response = client.put(
            "/marriages/77/start-date",
            json={
                "personAId": 11,
                "personBId": 33,
                "startDate": "2026-04-20",
            },
            cookies={"familiez_session": "ok"},
        )

        assert response.status_code == 200
        assert response.json() == {"success": True, "marriageId": 77}
        mock_connection.commit.assert_called_once()

    @patch("main.engine")
    def test_update_marriage_start_date_blocks_on_overlap_conflict(self, mock_engine, admin_session):
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        update_row = Mock()
        update_row._asdict.return_value = {
            "CompletedOk": 1,
            "Result": 409,
            "MarriageID": 77,
            "ErrorMessage": "Startdatum overlapt met een andere huwelijksperiode van een van beide partners",
        }
        update_proxy = Mock()
        update_proxy.fetchall.return_value = [update_row]

        mock_connection.execute.return_value = update_proxy

        response = client.put(
            "/marriages/77/start-date",
            json={
                "personAId": 11,
                "personBId": 33,
                "startDate": "2026-04-20",
            },
            cookies={"familiez_session": "ok"},
        )

        assert response.status_code == 409
        assert "overlapt" in response.json()["detail"]
        mock_connection.rollback.assert_called_once()

    @patch("main.engine")
    def test_update_marriage_start_date_returns_not_found_for_unknown_or_inactive_marriage(self, mock_engine, admin_session):
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        update_row = Mock()
        update_row._asdict.return_value = {
            "CompletedOk": 1,
            "Result": 404,
            "MarriageID": None,
            "ErrorMessage": "Geen actief huwelijk gevonden voor dit paar",
        }
        update_proxy = Mock()
        update_proxy.fetchall.return_value = [update_row]

        mock_connection.execute.return_value = update_proxy

        response = client.put(
            "/marriages/999999/start-date",
            json={
                "personAId": 11,
                "personBId": 33,
                "startDate": "2026-04-20",
            },
            cookies={"familiez_session": "ok"},
        )

        assert response.status_code == 404
        assert "Geen actief huwelijk" in response.json()["detail"]
        mock_connection.rollback.assert_called_once()
