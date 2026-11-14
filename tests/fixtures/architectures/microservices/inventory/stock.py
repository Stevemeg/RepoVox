import redis


def adjust(item):
    cache = redis.Redis(host="cache")
    cache.decr(item)
    return item
