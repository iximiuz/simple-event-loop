# Simple but workable event loop implementation in Python (< 100 LOC)

Example:
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

Check out the article about this code on my blog <a href="https://micromind.me/en/posts/explain-event-loop-in-100-lines-of-code/">Explain event loop in 100 lines of code</a>.

