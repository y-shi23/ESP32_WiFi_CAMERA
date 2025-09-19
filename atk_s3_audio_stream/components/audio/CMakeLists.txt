idf_component_register(
    SRCS
        "audio_codec.cc"
        "codecs/es8388_audio_codec.cc"
    INCLUDE_DIRS "include" "codecs"
    REQUIRES esp_codec_dev driver
)
