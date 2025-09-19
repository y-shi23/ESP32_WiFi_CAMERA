#pragma once
#include <cstdint>
#include <vector>
#include <string>

struct NetConfig {
    std::string host;
    uint16_t port;
};

class AudioCodec;

void start_stream_tasks(AudioCodec* codec, const NetConfig& cfg);

