import ipaddress
import dns.query


class Resolver:
    def __init__(self, upstream='1.1.1.1', timeout=2):
        address = ipaddress.ip_address(upstream)
        if address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError('DNS upstream must be a unicast IP outside loopback')
        self.upstream, self.timeout = str(address), timeout

    def resolve(self, query):
        return dns.query.udp_with_fallback(query, self.upstream, timeout=self.timeout)[0]
