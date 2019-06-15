## Simple but workable event loop in Python (< 100 LOC)

Check out the series about the event loop on my blog <a href="https://iximiuz.com/en/posts/explain-event-loop-in-100-lines-of-code/">Explain event loop in 100 lines of code</a> and <a href="https://iximiuz.com/en/posts/from-callback-hell-to-async-await-heaven/">From Callback Hell to async/await Heaven</a>.

### Example using callback-style:
```python
import socket as _socket

class EventLoop: pass

class Context: pass

class socket(Context): pass

def main(serv_addr):
    sock = socket(_socket.AF_INET, _socket.SOCK_STREAM)

    def _on_conn(err):
        if err:
            raise err

        def _on_sent(err):
            if err:
                sock.close()
                raise err

            def _on_resp(err, resp=None):
                sock.close()
                if err:
                    raise err
                print(resp)

            sock.recv(1024, _on_resp)

        sock.sendall(b'foobar', _on_sent)

    sock.connect(serv_addr, _on_conn)

if __name__ == '__main__':
    event_loop = EventLoop()
    Context.set_event_loop(event_loop)

    serv_addr = ('127.0.0.1', int(sys.argv[1]))
    event_loop.run(main, serv_addr)
```

Give it a try:
```bash
# server
> python server.py 53210

# client
> python event_loop.py 53210
```

### Example using async-await-like style:
```python
import socket as _socket

class EventLoop: pass

class Context: pass

class socket(Context): pass

def http_get(sock):
  try:
    yield sock.sendall(b'GET / HTTP/1.1\r\nHost: t.co\r\n\r\n')
    return sock.recv(1024)
  finally:
    sock.close()

def main(serv_addr):
  sock = socket(AF_INET, SOCK_STREAM)
  yield sock.connect(serv_addr)
  resp = yield http_get(sock)
  print(resp)

if __name__ == '__main__':
    event_loop = EventLoop()
    Context.set_event_loop(event_loop)

    serv_addr = ('t.co', 80)
    event_loop.run(main)
```

Give it a try:
```bash
> python event_loop_gen.py 53210
```
