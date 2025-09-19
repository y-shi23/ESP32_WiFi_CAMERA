#ifndef SETTINGS_STUB_H
#define SETTINGS_STUB_H

#include <string>
#include <unordered_map>

class Settings {
public:
    Settings(const char*, bool) {}
    int GetInt(const char* key, int def) {
        auto it = ints_.find(key);
        return it == ints_.end() ? def : it->second;
    }
    void SetInt(const char* key, int value) { ints_[key] = value; }
    std::string GetString(const char* key) { auto it = strs_.find(key); return it==strs_.end()?std::string():it->second; }
    void SetString(const char* key, const std::string& v) { strs_[key]=v; }
private:
    std::unordered_map<std::string,int> ints_;
    std::unordered_map<std::string,std::string> strs_;
};

#endif // SETTINGS_STUB_H

