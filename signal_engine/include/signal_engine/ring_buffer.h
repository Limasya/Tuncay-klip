#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// signal_engine/ring_buffer.h — Lock-free SPSC ring buffer for real-time audio
// ═══════════════════════════════════════════════════════════════════════════════
//
// Single-Producer Single-Consumer (SPSC) ring buffer.
// No locks, no allocation — safe for audio callback threads.
//
// Memory ordering: acquire-release on head/tail, relaxed on data.
// Cache-line aligned to avoid false sharing between producer and consumer.

#include <atomic>
#include <array>
#include <cstddef>
#include <cstring>
#include <type_traits>
#include <optional>

namespace se {

template<typename T, size_t Capacity>
class RingBuffer {
    static_assert((Capacity & (Capacity - 1)) == 0, "Capacity must be power of 2");
    static_assert(Capacity >= 2, "Capacity must be >= 2");

public:
    RingBuffer() : head_(0), tail_(0) {}

    // ── Producer side ─────────────────────────────────────────────────────────

    /// Try to write one element. Returns false if full.
    bool push(const T& item) {
        const size_t h = head_.load(std::memory_order_relaxed);
        const size_t next = (h + 1) & mask_;
        if (next == tail_.load(std::memory_order_acquire)) {
            return false; // full
        }
        data_[h] = item;
        head_.store(next, std::memory_order_release);
        return true;
    }

    /// Write a block of elements. Returns number actually written.
    size_t push_bulk(const T* items, size_t count) {
        size_t written = 0;
        while (written < count) {
            if (!push(items[written])) break;
            ++written;
        }
        return written;
    }

    // ── Consumer side ─────────────────────────────────────────────────────────

    /// Try to read one element. Returns nullopt if empty.
    std::optional<T> pop() {
        const size_t t = tail_.load(std::memory_order_relaxed);
        if (t == head_.load(std::memory_order_acquire)) {
            return std::nullopt; // empty
        }
        T item = data_[t];
        tail_.store((t + 1) & mask_, std::memory_order_release);
        return item;
    }

    /// Read a block of elements. Returns number actually read.
    size_t pop_bulk(T* out, size_t max_count) {
        size_t read = 0;
        while (read < max_count) {
            auto item = pop();
            if (!item.has_value()) break;
            out[read] = std::move(*item);
            ++read;
        }
        return read;
    }

    // ── Queries ───────────────────────────────────────────────────────────────

    size_t size() const noexcept {
        const size_t h = head_.load(std::memory_order_acquire);
        const size_t t = tail_.load(std::memory_order_acquire);
        return (h - t) & mask_;
    }

    bool empty() const noexcept { return head_.load(std::memory_order_acquire) == tail_.load(std::memory_order_acquire); }
    bool full() const noexcept { return ((head_.load(std::memory_order_acquire) + 1) & mask_) == tail_.load(std::memory_order_acquire); }
    static constexpr size_t capacity() { return Capacity; }

    void reset() noexcept {
        tail_.store(0, std::memory_order_relaxed);
        head_.store(0, std::memory_order_relaxed);
    }

private:
    static constexpr size_t mask_ = Capacity - 1;

    // Pad head/tail to separate cache lines (avoid false sharing)
    alignas(64) std::atomic<size_t> head_;
    alignas(64) std::atomic<size_t> tail_;
    alignas(64) std::array<T, Capacity> data_;
};

// ── Float ring buffer convenience alias ───────────────────────────────────────
using FloatRingBuffer = RingBuffer<float, 65536>;  // ~1.5s at 44100 Hz

} // namespace se
