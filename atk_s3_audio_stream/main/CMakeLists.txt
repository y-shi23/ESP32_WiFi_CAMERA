idf_component_register(
    SRCS
        "main.cc"
        "wifi.cc"
        "net_stream.cc"
    INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_netif esp_event nvs_flash driver esp_timer audio
)
