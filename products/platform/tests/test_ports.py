from agentplatform.ports import InMemoryBus, InMemoryCache, InMemoryStore


def test_one_key_always_lands_on_one_partition():
    bus = InMemoryBus()
    first = bus.publish("crm.tasks", "deal:4192", {"n": 1})
    second = bus.publish("crm.tasks", "deal:4192", {"n": 2})
    assert first.partition == second.partition
    assert (first.offset, second.offset) == (0, 1)


def test_messages_for_one_key_arrive_in_order():
    bus = InMemoryBus()
    for n in range(5):
        bus.publish("crm.tasks", "deal:4192", {"n": n})
    got = bus.poll("crm.tasks", "workers", limit=10)
    assert [m.value["n"] for m in got] == [0, 1, 2, 3, 4]


def test_polling_advances_the_group_cursor():
    bus = InMemoryBus()
    bus.publish("crm.tasks", "deal:1", {"n": 1})
    assert len(bus.poll("crm.tasks", "workers")) == 1
    assert bus.poll("crm.tasks", "workers") == []


def test_two_groups_read_the_same_topic_independently():
    bus = InMemoryBus()
    bus.publish("crm.events", "deal:1", {"n": 1})
    assert len(bus.poll("crm.events", "projector")) == 1
    assert len(bus.poll("crm.events", "audit")) == 1


def test_rewinding_replays_the_log():
    bus = InMemoryBus()
    bus.publish("crm.events", "deal:1", {"n": 1})
    bus.poll("crm.events", "audit")
    bus.rewind("crm.events", "audit")
    assert len(bus.poll("crm.events", "audit")) == 1


def test_lag_is_what_is_not_yet_acknowledged():
    """Polling is not finishing, so polling alone does not reduce lag.

    It used to: `poll` moved the committed offset itself, so a batch read and not
    yet processed counted as caught up. Lag read zero while the work was still
    outstanding, and `commit` - which the Bus protocol declares - had no callers
    anywhere in the repository.
    """
    bus = InMemoryBus()
    bus.publish("crm.tasks", "deal:1", {"n": 1})
    bus.publish("crm.tasks", "deal:2", {"n": 2})
    assert bus.lag("crm.tasks", "workers") == 2

    bus.poll("crm.tasks", "workers", limit=1)
    assert bus.lag("crm.tasks", "workers") == 2, "read, not acknowledged"
    assert bus.in_flight("crm.tasks", "workers") == 1

    bus.commit("crm.tasks", "workers")
    assert bus.lag("crm.tasks", "workers") == 1
    assert bus.in_flight("crm.tasks", "workers") == 0


def test_an_uncommitted_message_is_delivered_again_after_a_restart():
    """At-least-once, which is what a dead-letter queue downstream assumes.

    Before, a worker that polled and then died had consumed the message: the
    committed offset had already moved past it and nothing would ever hand it back.
    """
    bus = InMemoryBus()
    bus.publish("crm.tasks", "deal:1", {"n": 1})

    first = bus.poll("crm.tasks", "workers", limit=10)
    assert [m.value["n"] for m in first] == [1]
    assert bus.poll("crm.tasks", "workers", limit=10) == [], "not redelivered to a live reader"

    bus.restart("crm.tasks", "workers")  # the worker died before committing
    again = bus.poll("crm.tasks", "workers", limit=10)
    assert [m.value["n"] for m in again] == [1]

    bus.commit("crm.tasks", "workers")
    bus.restart("crm.tasks", "workers")
    assert bus.poll("crm.tasks", "workers", limit=10) == [], "acknowledged, so not again"


def test_committing_one_partition_leaves_the_rest_redeliverable():
    """A worker that handled part of a batch acknowledges only that part."""
    bus = InMemoryBus(partitions=4)
    for i in range(8):
        bus.publish("crm.tasks", f"deal:{i}", {"n": i})

    polled = bus.poll("crm.tasks", "workers", limit=10)
    assert len(polled) == 8
    done = polled[0].partition
    offsets = {done: max(m.offset for m in polled if m.partition == done) + 1}
    bus.commit("crm.tasks", "workers", offsets)

    bus.restart("crm.tasks", "workers")
    again = bus.poll("crm.tasks", "workers", limit=10)
    assert {m.partition for m in again} == {m.partition for m in polled} - {done}


def test_the_store_copies_rather_than_aliasing():
    store = InMemoryStore()
    row = {"a": 1}
    store.put("runs", "r1", row)
    row["a"] = 2
    assert store.get("runs", "r1") == {"a": 1}


def test_add_is_the_lock_primitive():
    cache = InMemoryCache()
    assert cache.add("lock:deal:1", "worker-a") is True
    assert cache.add("lock:deal:1", "worker-b") is False
    cache.delete("lock:deal:1")
    assert cache.add("lock:deal:1", "worker-b") is True


def test_the_in_memory_lock_is_granted_once_under_contention():
    """`add` is the lock, and it used to be a check and a set with a gap between.

    Products run several threads against one of these; swarm-lab's "work is done
    exactly once at every N" is produced by this method whenever Redis is not up. I
    could not make it double-grant on this build - 400 trials, eight contending
    threads, switch interval at a nanosecond - which is why it is guarded rather
    than left correct by an implementation detail of the GIL.
    """
    import sys
    import threading

    cache_class = InMemoryCache
    granted = 0
    tally = threading.Lock()
    was = sys.getswitchinterval()
    sys.setswitchinterval(1e-9)
    try:
        for _ in range(200):
            cache = cache_class()
            at_once = threading.Barrier(8)

            def grab(cache=cache, at_once=at_once):
                nonlocal granted
                at_once.wait()
                if cache.add("k", "v"):
                    with tally:
                        granted += 1

            threads = [threading.Thread(target=grab) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
    finally:
        sys.setswitchinterval(was)

    assert granted == 200, f"the lock was granted {granted} times across 200 trials"


def test_the_lock_is_released_by_deleting_the_key():
    cache = InMemoryCache()
    assert cache.add("k", "a") is True
    assert cache.add("k", "b") is False
    cache.delete("k")
    assert cache.add("k", "b") is True
    assert cache.get("k") == "b"
