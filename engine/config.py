from openeogeotrellis.config import GpsBackendConfig
config = GpsBackendConfig(
    id="private-gee-local", layer_catalog_files=[], oidc_providers=[],
    enable_basic_auth=False, enable_oidc_auth=False, opensearch_enrich=False,
    default_opensearch_endpoint="http://127.0.0.1:9/disabled",
    logging_es_hosts=[], vault_addr=None, etl_api=None, etl_api_config=None,
    use_etl_api_on_sync_processing=False, etl_api_report_added_value_on_sync_processing=False,
    ejr_api=None, workspaces={},
)
