from whisky.bootstrap.api import create_app


def test_download_exposes_an_independent_versioned_export_schema():
    schema = create_app().openapi()
    response = schema["paths"]["/api/v1/library/export"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AccountExportViewV1"
    }
