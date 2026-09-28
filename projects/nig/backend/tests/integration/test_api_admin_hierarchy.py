from typing import Any, Dict

import orjson
from faker import Faker
from nig.tests import TestEnv, test_env  # noqa: F401
from restapi.config import API_URL
from restapi.connectors import Connector
from restapi.services.authentication import BaseAuthentication, Role
from restapi.tests import API_URI, AUTH_URI, BaseTests, FlaskClient
from restapi.utilities.logs import Events


class TestApp(BaseTests):
    def _create_staff_as_staff(
        self,
        client: FlaskClient,
        faker: Faker,
        headers: Dict[str, str],
        group_uuid: str,
    ) -> Dict[str, Any]:
        schema = self.get_dynamic_input_schema(client, "admin/users", headers)
        data = self.buildData(schema)
        data.update(
            {
                "email": faker.ascii_email(),
                "password": faker.password(
                    BaseAuthentication.MIN_PASSWORD_LENGTH + 4, strong=True
                ),
                "group": group_uuid,
                "roles": orjson.dumps([Role.STAFF.value]).decode("utf-8"),
                "email_notification": False,
                "is_active": True,
                "expiration": None,
            }
        )
        response = client.post(f"{API_URI}/admin/users", json=data, headers=headers)
        assert response.status_code == 200
        return {"uuid": self.get_content(response), **data}

    def test_admin_hierarchy_matrix(
        self,
        client: FlaskClient,
        faker: Faker,
        test_env: TestEnv,  # noqa: F811
    ) -> None:
        (
            root_headers,
            group_a,
            normal_uuid,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
        ) = test_env.setup(study=False)
        root_headers, _ = self.do_login(client, None, None)
        assert root_headers is not None

        create_schema = self.get_dynamic_input_schema(
            client, "admin/users", root_headers
        )
        roles_field = next(field for field in create_schema if field["key"] == "roles")
        role_options = set(roles_field["options"])
        assert Role.ADMIN.value not in role_options
        assert role_options == {
            Role.STAFF.value,
            Role.COORDINATOR.value,
            Role.USER.value,
        }

        staff_uuid, staff_data = self.create_user(
            client, data={"group": group_a}, roles=[Role.STAFF]
        )
        test_env.user_uuids.append(staff_uuid)
        staff_headers, _ = self.do_login(
            client, staff_data["email"], staff_data["password"]
        )

        peer = self._create_staff_as_staff(client, faker, staff_headers, group_a)
        peer_uuid = str(peer["uuid"])
        test_env.user_uuids.append(peer_uuid)

        # The supplemental hierarchy audit entry must not hide the canonical
        # framework User creation event from existing audit consumers.
        events = self.get_last_events(1, filters={"target_type": "User"})
        assert events[0].event == Events.create.value
        assert events[0].target_id == peer_uuid

        response = client.get(f"{API_URI}/admin/users", headers=staff_headers)
        assert response.status_code == 200
        visible = self.get_content(response)
        assert isinstance(visible, list)
        emails = {item["email"] for item in visible}
        assert peer["email"].lower() in emails
        assert BaseAuthentication.default_user not in emails

        response = client.put(
            f"{API_URI}/admin/users/{peer_uuid}",
            json={"name": "Permitted", "email": faker.ascii_email()},
            headers=staff_headers,
        )
        assert response.status_code == 204

        forbidden_updates = (
            {"is_active": False},
            {"expiration": faker.future_datetime().isoformat()},
            {"roles": orjson.dumps([Role.USER.value]).decode("utf-8")},
            {"password": faker.password(strong=True)},
        )
        for payload in forbidden_updates:
            response = client.put(
                f"{API_URI}/admin/users/{peer_uuid}",
                json=payload,
                headers=staff_headers,
            )
            assert response.status_code == 403

        response = client.delete(
            f"{API_URI}/admin/users/{peer_uuid}", headers=staff_headers
        )
        assert response.status_code == 403
        response = client.put(
            f"{API_URI}/admin/users/{staff_uuid}",
            json={"is_active": False},
            headers=staff_headers,
        )
        assert response.status_code == 403
        response = client.delete(
            f"{API_URI}/admin/users/{staff_uuid}", headers=staff_headers
        )
        assert response.status_code == 403

        response = client.get(f"{AUTH_URI}/profile", headers=root_headers)
        assert response.status_code == 200
        root_uuid = str(self.get_content(response)["uuid"])
        response = client.put(
            f"{API_URI}/admin/users/{root_uuid}",
            json={"name": "Hidden Root"},
            headers=staff_headers,
        )
        assert response.status_code == 404

        response = client.put(
            f"{API_URI}/admin/users/{root_uuid}",
            json={"name": "Immutable Root"},
            headers=root_headers,
        )
        assert response.status_code == 403
        response = client.delete(
            f"{API_URI}/admin/users/{root_uuid}", headers=root_headers
        )
        assert response.status_code == 403

        # Staff keeps the framework powers over non-Staff users.
        response = client.put(
            f"{API_URI}/admin/users/{normal_uuid}",
            json={"is_active": False},
            headers=staff_headers,
        )
        assert response.status_code == 204

        # Root can demote Staff; every existing token for that account is revoked.
        auth = Connector.get_authentication_instance()
        staff_user = auth.get_user(user_id=staff_uuid)
        assert staff_user is not None
        assert auth.get_tokens(user=staff_user)
        response = client.put(
            f"{API_URI}/admin/users/{staff_uuid}",
            json={"roles": orjson.dumps([Role.USER.value]).decode("utf-8")},
            headers=root_headers,
        )
        assert response.status_code == 204
        assert auth.get_tokens(user=staff_user) == []

    def test_admin_hierarchy_routes_and_openapi(self, client: FlaskClient) -> None:
        from restapi.endpoints.admin_users import AdminUsers

        assert AdminUsers.post.__module__ == "nig.endpoints.admin_users"
        assert AdminUsers.put.__module__ == "nig.endpoints.admin_users"
        assert AdminUsers.delete.__module__ == "nig.endpoints.admin_users"

        collection_rules = [
            rule
            for rule in client.application.url_map.iter_rules()
            if rule.rule.rstrip("/") == f"{API_URL}/admin/users"
        ]
        item_rules = [
            rule
            for rule in client.application.url_map.iter_rules()
            if rule.rule.rstrip("/") == f"{API_URL}/admin/users/<user_id>"
        ]
        assert len([rule for rule in collection_rules if "POST" in rule.methods]) == 1
        assert len([rule for rule in item_rules if "PUT" in rule.methods]) == 1
        assert len([rule for rule in item_rules if "DELETE" in rule.methods]) == 1

        headers, _ = self.do_login(client, None, None)
        response = client.get(f"{API_URI}/specs", headers=headers)
        assert response.status_code == 200
        specs = self.get_content(response)
        collection = specs["paths"][AdminUsers.post.uri]
        item_path = AdminUsers.put.uri.replace("<user_id>", "{user_id}")
        item = specs["paths"][item_path]
        assert "post" in collection
        assert "put" in item
        assert "delete" in item
        assert "403" in collection["post"]["responses"]
        assert "403" in item["put"]["responses"]
        assert "403" in item["delete"]["responses"]

        profile = client.get(f"{AUTH_URI}/profile", headers=headers)
        assert profile.status_code == 200
        root_uuid = str(self.get_content(profile)["uuid"])
        put_schema = self.get_dynamic_input_schema(
            client, f"admin/users/{root_uuid}", headers, method="put"
        )
        fields = {field["key"]: field for field in put_schema}
        assert "email" in fields
        assert not fields["email"]["required"]
        role_options = set(fields["roles"]["options"])
        assert Role.ADMIN.value not in role_options
