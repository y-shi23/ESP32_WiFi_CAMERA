#include <cstdio>
#include <cstring>
#include <string>
#include <esp_log.h>
#include <driver/i2c_master.h>
#include <driver/gpio.h>

#include "wifi.h"
#include "net_stream.h"

#include "es8388_audio_codec.h"

static const char* TAG = "main";

// ATK-DNESP32S3 audio pins and params (from repo config)
static constexpr int INPUT_SR = 24000;
static constexpr int OUTPUT_SR = 24000;

static constexpr gpio_num_t PIN_MCLK = GPIO_NUM_3;
static constexpr gpio_num_t PIN_WS   = GPIO_NUM_9;
static constexpr gpio_num_t PIN_BCLK = GPIO_NUM_46;
static constexpr gpio_num_t PIN_DIN  = GPIO_NUM_14; // MIC -> ESP DIN
static constexpr gpio_num_t PIN_DOUT = GPIO_NUM_10; // ESP DOUT -> SPK

static constexpr gpio_num_t I2C_SDA = GPIO_NUM_41;
static constexpr gpio_num_t I2C_SCL = GPIO_NUM_42;
static constexpr uint8_t ES8388_ADDR = ES8388_CODEC_DEFAULT_ADDR;

// Configurable via menuconfig (defaults provided in Kconfig)
#ifndef CONFIG_STREAM_SERVER_HOST
#define CONFIG_STREAM_SERVER_HOST "192.168.1.2"
#endif
#ifndef CONFIG_STREAM_SERVER_PORT
#define CONFIG_STREAM_SERVER_PORT 9002
#endif

extern "C" void app_main(void) {
    ESP_LOGI(TAG, "Starting atk_s3_audio_stream");

    if (!wifi_init_and_connect()) {
        ESP_LOGE(TAG, "WiFi connect failed");
        return;
    }

    // I2C bus for ES8388
    i2c_master_bus_handle_t i2c_bus = nullptr;
    i2c_master_bus_config_t i2c_bus_cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = I2C_SDA,
        .scl_io_num = I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .intr_priority = 0,
        .trans_queue_depth = 0,
        .flags = { .enable_internal_pullup = 1 },
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&i2c_bus_cfg, &i2c_bus));

    static Es8388AudioCodec audio_codec(
        i2c_bus,
        I2C_NUM_0,
        INPUT_SR,
        OUTPUT_SR,
        PIN_MCLK,
        PIN_BCLK,
        PIN_WS,
        PIN_DOUT,
        PIN_DIN,
        GPIO_NUM_NC,
        ES8388_ADDR,
        false /* input_reference */
    );

    audio_codec.Start();

    NetConfig cfg{ std::string(CONFIG_STREAM_SERVER_HOST), (uint16_t)CONFIG_STREAM_SERVER_PORT };
    start_stream_tasks(&audio_codec, cfg);
}

