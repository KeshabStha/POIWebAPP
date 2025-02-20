def getUrl():
    import hmac
    import hashlib
    import base64
    import time
    import urllib.parse
    import urllib.request

    def make_signature_hmac(http_method, parameter, uri, secret):
        # http_method
        http_method = http_method.upper()

        # Remove existing oauth_signature if present
        if 'oauth_signature' in parameter:
            del parameter['oauth_signature']
        
        # Sort and encode parameters
        params = urllib.parse.urlencode(sorted(parameter.items(),key=lambda x:x[0]))
        
        # Parse URI
        parts = urllib.parse.urlparse(uri)
        scheme = parts.scheme if parts.scheme else 'http'
        port = '443' if scheme == 'https' else '80'
        host = parts.netloc
        path = parts.path
        uri = scheme + '://' + host + path

        # Append '&' to the secret key
        secret += '&'

        # Create base string
        base_string = http_method + '&' + urllib.parse.quote(uri, '') + '&' + urllib.parse.quote(params, '')

        # Generate HMAC-SHA1 signature
        signature = hmac.new(secret.encode(), base_string.encode(), hashlib.sha1).digest()

        # Base64 encode the signature
        signature1 = base64.b64encode(signature)
        parameter['oauth_signature'] = signature1.decode()

    # Example usage
    http_method = 'GET'
    parameter = {
    'key':'JSZ177163895ed5|F0HI1',
    'api':'zdcmap.js,control.js',
    'enc':'UTF8',
    'if_clientid':'JSZ177163895ed5|F0HI1',
    'auth_type':'oauth',
    'oauth_consumer_key':'JSZ177163895ed5|F0HI1',
    'oauth_version': '1.0',
    'oauth_timestamp': int(time.time()),
    'oauth_nonce': 'Keshab',
    'oauth_signature_method': 'HMAC-SHA1',
    'oauth_signature':'' 
    }
    uri = 'https://test.api.its-mo.com/v3/loader'
    secret = 'GV47rV760ElxH0RZFEYljx3L9fg'
    # Generate signed parameters
    make_signature_hmac(http_method, parameter, uri, secret)

    # Construct the URL with signed parameters
    url = uri + '?' + urllib.parse.urlencode(parameter)
    # Make the API request
    try:
        result = urllib.request.urlopen(url).read()
        return url
    except ValueError:
        print('Failed to access the API.')
    except IOError:
        print('Authentication failed.')
if __name__ == "__main__":
    getUrl()