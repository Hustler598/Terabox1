import redis
import logging
import socket
import time

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
def test_redis_connection():
    # Railway Redis URL format
    REDIS_URL = "redis://default:YVLDcQcGZZGaeXimnYiSIrdYhTYfSOpV@roundhouse.proxy.rlwy.net:34496"
    
    log.info("Testing with Redis URL:")
    log.info(f"REDIS_URL: {REDIS_URL.replace(REDIS_URL.split('@')[0], 'redis://***')}")

    try:
        # Create Redis client from URL
        log.info("\nInitializing Redis client...")
        start_time = time.time()
        
        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_timeout=10,
            socket_connect_timeout=10,
            socket_keepalive=True,
            health_check_interval=30,
            retry_on_timeout=True
        )
        
        # Test connection
        log.info("Testing connection...")
        response = client.ping()
        log.info(f"Ping response: {response}")
        
        # Test basic operations
        log.info("\nTesting basic Redis operations...")
        test_result = client.set('test_key', 'test_value', ex=300)  # 5 minutes expiration
        log.info(f"Set operation result: {test_result}")
        
        value = client.get('test_key')
        log.info(f"Get operation result: {value}")
        
        # List existing keys
        log.info("\nListing existing keys:")
        keys = client.keys('*')
        log.info(f"Found {len(keys)} keys")
        for key in keys[:5]:  # Show first 5 keys only
            value = client.get(key)
            log.info(f"Key: {key}, Value: {value}")
    except redis.TimeoutError as e:
        log.error(f"Connection timed out: {str(e)}")
        log.error("Please check if Redis service is running and accessible")
    except redis.ConnectionError as e:
        log.error(f"Connection error: {str(e)}")
        log.error("Please verify Redis connection details and network connectivity")
    except Exception as e:
        log.error(f"Unexpected error: {str(e)}")
        log.error("Full error details:", exc_info=True)
    finally:
        duration = time.time() - start_time
        log.info(f"\nExecution completed in {duration:.2f} seconds")

if __name__ == "__main__":
    test_redis_connection() 
