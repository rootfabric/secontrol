from secontrol import RedisEventClient


def test_client_can_be_instantiated_without_args():
    client = RedisEventClient()
    assert client.client is not None
    client.close()
