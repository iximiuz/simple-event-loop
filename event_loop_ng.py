# python3

import collections
import errno
import heapq
import json
import random
import selectors
import socket as _socket
import sys
import time
import types


class EventLoop:
    def __init__(self):
        self._queue = Queue()
        self._time = None

    def run(self, entry_point, *args):
        self._execute(entry_point, *args)

        while not self._queue.is_empty():
            fn, mask = self._queue.pop(self._time)
            self._execute(fn, mask)

        self._queue.close()

    def register_fileobj(self, fileobj, callback):
        self._queue.register_fileobj(fileobj, callback)

    def unregister_fileobj(self, fileobj):
        self._queue.unregister_fileobj(fileobj)

    def set_timer(self, duration):
        p = Promise()
        self._time = hrtime()
        self._queue.register_timer(self._time + duration,
                                   lambda _: p._resolve())
        return p

    def _execute(self, callback, *args):
        self._time = hrtime()
        try:
            # unwind(callback(*args)).catch(
            #        lambda e: print('Uncaught rejection:', e))
            ret = callback(*args)
            if is_generator(ret):
                unwind2(ret, 
                        ok=lambda *_: None, 
                        fail=lambda e: print('Uncaught rejection:', e))

        except Exception as err:
            print('Uncaught exception:', err)
        self._time = hrtime()


class Queue:
    def __init__(self):
        self._selector = selectors.DefaultSelector()
        self._timers = []
        self._timer_no = 0
        self._ready = collections.deque()

    def register_timer(self, tick, callback):
        timer = (tick, self._timer_no, callback)
        heapq.heappush(self._timers, timer)
        self._timer_no += 1

    def register_fileobj(self, fileobj, callback):
        self._selector.register(fileobj,
                selectors.EVENT_READ | selectors.EVENT_WRITE,
                callback)

    def unregister_fileobj(self, fileobj):
        self._selector.unregister(fileobj)

    def pop(self, tick):
        if self._ready:
            return self._ready.popleft()

        timeout = None
        if self._timers:
            timeout = (self._timers[0][0] - tick) / 10e6

        events = self._selector.select(timeout)
        for key, mask in events:
            callback = key.data
            self._ready.append((callback, mask))

        if not self._ready and self._timers:
            idle = (self._timers[0][0] - tick)
            if idle > 0:
                time.sleep(idle / 10e6)
                return self.pop(tick + idle)

        while self._timers and self._timers[0][0] <= tick:
            _, _, callback = heapq.heappop(self._timers)
            self._ready.append((callback, None))

        return self._ready.popleft()

    def is_empty(self):
        return not (self._ready or self._timers or self._selector.get_map())

    def close(self):
        self._selector.close()


class Context:
    _event_loop = None

    @classmethod
    def set_event_loop(cls, event_loop):
        cls._event_loop = event_loop

    @property
    def evloop(self):
        return self._event_loop


def unwind2(gen, ok, fail, ret=None, method='send'):
    try:
        ret = getattr(gen, method)(ret)
    except StopIteration as stop:
        return ok(stop.value)
    except Exception as e:
        return fail(e)

    if is_generator(ret):
        unwind2(ret,
                ok=lambda x: unwind2(gen, ok, fail, x),
                fail=lambda e: unwind2(gen, ok, fail, e, 'throw'))
    elif is_promise(ret):
        ret.then(lambda x=None: unwind2(gen, ok, fail, x)) \
           .catch(lambda e: unwind2(gen, ok, fail, e, 'throw'))
    else:
        wait_all(ret, 
                lambda x=None: unwind2(gen, ok, fail, x),
                lambda e: unwind2(gen, ok, fail, e, 'throw'))


def wait_all(col, ok, fail):
    counter = len(col)
    results = [None] * counter

    def _resolve_single(i):

        def _do_resolve(val):
            nonlocal counter
            results[i] = val
            counter -= 1
            if counter == 0:
                ok(results)

        return _do_resolve

    for i, c in enumerate(col):
        if is_generator(c):
            unwind2(c, ok=_resolve_single(i), fail=fail)
            continue

        if is_promise(c):
            c.then(_resolve_single(i)).catch(fail)
            continue

        raise Exception('Only promise or generator '
                        'can be yielded to event loop')


def unwind(gen):
    p = Promise()
    if not is_generator(gen):
        p._resolve(gen)
        return p

    def _on_fulfilled(res=None):
        ret = None
        try:
            ret = gen.send(res)
        except StopIteration as stop:
            return p._resolve(stop.value)
        except Exception as exc:
            return p._reject(exc)
        _next(ret)

    def _on_rejected(err):
        ret = None
        try:
            ret = gen.throw(err)
        except StopIteration as stop:
            return p._resolve(stop.value)
        except Exception as exc:
            return p._reject(exc)
        _next(ret)

    def _next(ret):
        nextp = to_promise(ret)
        if not nextp:
            return _on_rejected(Exception('Only promise or generator '
                                          'can be yielded to event loop'))
        nextp.then(_on_fulfilled)
        nextp.catch(_on_rejected)

    _on_fulfilled()
    return p


def to_promise(val):
    if is_promise(val):
        return val

    if is_generator(val):
        return unwind(val)

    if isinstance(val, list):
        promises = [to_promise(x) for x in val]
        if len(val) == len(list(filter(None, promises))):
            return Promise.all(promises)

    return None


def is_generator(val):
    return isinstance(val, types.GeneratorType)


def is_promise(val):
    return isinstance(val, Promise)


class Promise(Context):
    def __init__(self):
        self._on_resolve = []
        self._on_reject = []
        self._resolved = False
        self._rejected = False
        self._value = None

    @classmethod
    def all(cls, promises):
        pall = cls()
        counter = len(promises)
        if counter == 0:
            pall._resolve()
            return pall

        results = [None] * counter
        def _on_single_resolved(i):
            def _cb(*args):
                nonlocal counter

                results[i] = args
                counter -= 1
                if counter == 0:
                    pall._resolve(results)

            return _cb

        for idx, p in enumerate(promises):
            p.then(_on_single_resolved(idx))
            p.catch(pall._reject)

        return pall

    def then(self, cb):
        if self._resolved:
            self.evloop._execute(cb, *self._value)
        elif not self._rejected:
            self._on_resolve.append(cb)
        return self

    def catch(self, cb):
        if self._rejected:
            self.evloop._execute(cb, self._value)
        elif not self._resolved:
            self._on_reject.append(cb)
        return self

    def _resolve(self, *args):
        if self._resolved or self._rejected:
            return

        self._resolved = True
        self._value = args
        for cb in self._on_resolve:
            self.evloop._execute(cb, *args)

    def _reject(self, err):
        if self._resolved or self._rejected:
            return
        self._rejected = True
        self._value = err
        for cb in self._on_reject:
            cb(err)
    

class IOError(Exception):
    def __init__(self, message, errorno, errorcode):
        super().__init__(message)
        self.errorno = errorno
        self.errorcode = errorcode

    def __str__(self):
        return super().__str__() + f' (error {self.errorno} {self.errorcode})'


def hrtime():
    return int(time.time() * 10e6)


def sleep(duration):
    return Context._event_loop.set_timer(duration * 10e3)


class socket(Context):
    def __init__(self, *args):
        self._sock = _socket.socket(*args)
        self._sock.setblocking(False)
        self.evloop.register_fileobj(self._sock, self._on_event)
        # 0 - initial
        # 1 - connecting
        # 2 - connected
        # 3 - closed
        self._state = 0 
        self._callbacks = {}

    def connect(self, addr):
        assert self._state == 0
        self._state = 1

        p = Promise()
        def _on_conn(err):
            if err:
                p._reject(err)
            else:
                p._resolve()

        self._callbacks['conn'] = _on_conn
        err = self._sock.connect_ex(addr)
        assert errno.errorcode[err] == 'EINPROGRESS'
        return p

    def recv(self, n):
        assert self._state == 2
        assert 'recv' not in self._callbacks

        p = Promise()
        def _on_read_ready(err):
            if err:
                p._reject(err)
            else:
                data = self._sock.recv(n)
                p._resolve(data)

        self._callbacks['recv'] = _on_read_ready
        return p

    def sendall(self, data):
        assert self._state == 2
        assert 'sent' not in self._callbacks

        p = Promise()
        def _on_write_ready(err):
            nonlocal data
            if err:
                return p._reject(err)
            
            n = self._sock.send(data)
            if n < len(data):
                data = data[n:]
                self._callbacks['sent'] = _on_write_ready
            else:
                p._resolve(None)

        self._callbacks['sent'] = _on_write_ready
        return p

    def close(self):
        self.evloop.unregister_fileobj(self._sock)
        self._callbacks.clear()
        self._state = 3
        self._sock.close()

    def _on_event(self, mask):
        if self._state == 1:
            assert mask == selectors.EVENT_WRITE
            cb = self._callbacks.pop('conn')
            err = self._get_sock_error()
            if err:
                self.close()
            else:
                self._state = 2
            cb(err)

        if mask & selectors.EVENT_READ:
            cb = self._callbacks.get('recv')
            if cb:
                del self._callbacks['recv']
                err = self._get_sock_error()
                cb(err)

        if mask & selectors.EVENT_WRITE:
            cb = self._callbacks.get('sent')
            if cb:
                del self._callbacks['sent']
                err = self._get_sock_error()
                cb(err)

    def _get_sock_error(self):
        err = self._sock.getsockopt(_socket.SOL_SOCKET, 
                                    _socket.SO_ERROR)
        if not err:
            return None
        return IOError('connection failed', 
                       err, errno.errorcode[err])

###############################################################################

class Client:
    def __init__(self, addr):
        self.addr = addr

    def get_user(self, user_id):
        return self._get(f'GET user {user_id}\n')

    def get_balance(self, account_id):
        return self._get(f'GET account {account_id}\n')

    def _get(self, req):
        sock = socket(_socket.AF_INET, _socket.SOCK_STREAM)
        yield sock.connect(self.addr)
        try:
            yield sock.sendall(req.encode('utf8'))
            resp = yield sock.recv(1024)
            return json.loads(resp)
        finally:
            sock.close()


def get_user_balance(serv_addr, user_id):
    yield sleep(random.randint(0, 1000))

    client = Client(serv_addr)
    user = yield client.get_user(user_id)
    if user_id % 5 == 0:
        raise Exception('It is OK to throw here')
    acc = yield client.get_balance(user['account_id'])
    return f'User {user["name"]} has {acc["balance"]} USD'


def print_balance(serv_addr, user_id):
    try:
        balance = yield get_user_balance(serv_addr, user_id)
        print(balance)
    except Exception as exc:
        print('Catched:', exc)


def main(serv_addr):
    def on_sleep():
        b = yield get_user_balance(serv_addr, 1)
        print('side flow:', b)
    sleep(5000).then(on_sleep)

    tasks = []
    for i in range(10):
        tasks.append(print_balance(serv_addr, i))
    yield tasks


if __name__ == '__main__':
    event_loop = EventLoop()
    Context.set_event_loop(event_loop)

    serv_addr = ('127.0.0.1', int(sys.argv[1]))
    event_loop.run(main, serv_addr)

