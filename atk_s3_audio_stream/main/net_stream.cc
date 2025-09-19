#include "net_stream.h"
#include "audio_codec.h"

#include <lwip/sockets.h>
#include <lwip/netdb.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <cstring>

static const char* TAG = "net_stream";

// Packet header: magic 'PCM0', type(1=mic_up,2=spk_down), len (bytes)
struct __attribute__((packed)) PcmHeader {
    uint32_t magic;
    uint8_t type;
    uint16_t len;
};
static constexpr uint32_t PCM_MAGIC = 0x304D4350u; // 'PCM0'

static bool send_all(int sock, const uint8_t* data, size_t len) {
    size_t sent = 0;
    while (sent < len) {
        int ret = ::send(sock, (const char*)data + sent, (int)(len - sent), 0);
        if (ret <= 0) return false;
        sent += (size_t)ret;
    }
    return true;
}

static bool recv_all(int sock, uint8_t* data, size_t len) {
    size_t recvd = 0;
    while (recvd < len) {
        int ret = ::recv(sock, (char*)data + recvd, (int)(len - recvd), 0);
        if (ret <= 0) return false;
        recvd += (size_t)ret;
    }
    return true;
}

static int connect_to(const NetConfig& cfg) {
    struct addrinfo hints = {};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    struct addrinfo* res = nullptr;
    char portstr[16];
    snprintf(portstr, sizeof(portstr), "%u", cfg.port);
    int err = getaddrinfo(cfg.host.c_str(), portstr, &hints, &res);
    if (err != 0 || !res) {
        ESP_LOGE(TAG, "getaddrinfo failed: %d", err);
        return -1;
    }
    int sock = ::socket(res->ai_family, res->ai_socktype, 0);
    if (sock < 0) {
        freeaddrinfo(res);
        ESP_LOGE(TAG, "socket create failed");
        return -1;
    }
    if (::connect(sock, res->ai_addr, res->ai_addrlen) != 0) {
        ESP_LOGE(TAG, "connect failed");
        ::close(sock);
        freeaddrinfo(res);
        return -1;
    }
    freeaddrinfo(res);
    ESP_LOGI(TAG, "Connected to %s:%u", cfg.host.c_str(), cfg.port);
    return sock;
}

static void mic_uplink_task(void* arg) {
    auto* pair = static_cast<std::pair<AudioCodec*, NetConfig>*>(arg);
    AudioCodec* codec = pair->first;
    NetConfig cfg = pair->second;
    delete pair;

    const int sample_rate = codec->input_sample_rate();
    const size_t frame_samples = sample_rate / 50; // 20ms
    std::vector<int16_t> frame(frame_samples * codec->input_channels());

    while (true) {
        int sock = connect_to(cfg);
        if (sock < 0) {
            vTaskDelay(pdMS_TO_TICKS(2000));
            continue;
        }

        // Identify stream direction
        {
            const char hello[] = "HELLO-UP"; // uplink (mic)
            send_all(sock, (const uint8_t*)hello, sizeof(hello)-1);
        }

        while (true) {
            if (!codec->input_enabled()) codec->EnableInput(true);
            if (!codec->InputData(frame)) { vTaskDelay(pdMS_TO_TICKS(5)); continue; }

            PcmHeader hdr{ PCM_MAGIC, 0x01, (uint16_t)(frame.size() * sizeof(int16_t)) };
            if (!send_all(sock, (uint8_t*)&hdr, sizeof(hdr))) break;
            if (!send_all(sock, (uint8_t*)frame.data(), frame.size() * sizeof(int16_t))) break;
        }
        ::close(sock);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

static void spk_downlink_task(void* arg) {
    auto* pair = static_cast<std::pair<AudioCodec*, NetConfig>*>(arg);
    AudioCodec* codec = pair->first;
    NetConfig cfg = pair->second;
    delete pair;

    while (true) {
        int sock = connect_to(cfg);
        if (sock < 0) { vTaskDelay(pdMS_TO_TICKS(2000)); continue; }

        // Identify stream direction
        {
            const char hello[] = "HELLO-DOWN"; // downlink (speaker)
            send_all(sock, (const uint8_t*)hello, sizeof(hello)-1);
        }
        // Read loop (speaker data from server)
        while (true) {
            PcmHeader hdr{};
            if (!recv_all(sock, (uint8_t*)&hdr, sizeof(hdr))) break;
            if (hdr.magic != PCM_MAGIC || hdr.type != 0x02 || hdr.len == 0) {
                ESP_LOGW(TAG, "Invalid packet: magic=%08x type=%u len=%u", hdr.magic, hdr.type, hdr.len);
                break;
            }
            std::vector<int16_t> buf(hdr.len / sizeof(int16_t));
            if (!recv_all(sock, (uint8_t*)buf.data(), hdr.len)) break;
            if (!codec->output_enabled()) codec->EnableOutput(true);
            codec->OutputData(buf);
        }
        ::close(sock);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void start_stream_tasks(AudioCodec* codec, const NetConfig& cfg) {
    // Two separate connections (uplink/downlink) keep roles simple.
    auto* up = new std::pair<AudioCodec*, NetConfig>(codec, cfg);
    xTaskCreate(&mic_uplink_task, "mic_uplink", 4096, up, 5, nullptr);
    auto* dn = new std::pair<AudioCodec*, NetConfig>(codec, cfg);
    xTaskCreate(&spk_downlink_task, "spk_downlink", 4096, dn, 5, nullptr);
}
