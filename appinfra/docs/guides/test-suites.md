# Test Suites

Every test belongs to exactly one suite. The suite is decided by what the test touches, not by
what it is about: a test of pure parsing logic that writes its input to a temporary file is an
integration test.

## Definitions

| Suite | Runs in | May touch | Directory |
|-------|---------|-----------|-----------|
| `unit` | one process | memory only | `tests/unit/` |
| `integration` | one machine | processes, threads, files, localhost services, databases, signals, timers | `tests/integration/` |
| `e2e` | one machine | an entry point started as its own process | `tests/e2e/` |
| `security` | by purpose | security behaviour (injection, validation) | `tests/security/` |
| `performance` | by purpose | benchmarks | `tests/performance/` |

### Unit

A unit test stays in one process and one thread and, in principle, could run at the same time as
any other unit test in that process. The rules below follow from that: a test that does I/O, uses
other threads, or touches process-wide state depends on something outside its control or changes
what another test sees. A unit test must not:

- **perform I/O**: files (`tmp_path` included), sockets, subprocesses, databases, file watchers;
- **use another thread**: start one, hand work to one (a thread pool, `run_in_executor`,
  `asyncio.to_thread`) or wait on one, including the threads the code under test starts. An
  `asyncio` event loop runs on the test's own thread and is allowed;
- **use or change process-wide state that outlives the test**: signal handlers, interval timers
  (`setitimer`, `alarm`).

A sleep does not make a test an integration test: it depends on nothing outside the test. Waiting
on real time is a matter of [timing](#timing), which applies to every suite alike.

The criterion enforced is narrower than the principle: a unit test neither depends on
process-wide state nor leaves it changed. Test-scoped patching (`unittest.mock.patch`,
`monkeypatch`) and output capture (`capsys`, `caplog`) replace process-wide objects for the length
of one test and are allowed: pytest restores them, and pytest-xdist runs one test at a time in
each worker process. The allowance is for a limitation of these tools, not an exception to the
principle: they replace module attributes, `sys.stdout` or `os.environ`, which every thread in the
process shares, so tests that use them can run in parallel across processes but not in one. New
code favours injecting a dependency over patching a module attribute,
which keeps its tests parallel-safe in the strict sense too.

Code under test that does any of the above is mocked at the call site, for example by patching
`alarm_timeout` where the module under test imports it.

The test runner's own bookkeeping does not count. pytest-asyncio runs each coroutine test in an
`asyncio.Runner`, which swaps the SIGINT handler for the duration of the run and restores it; the
test neither depends on that handler nor leaves it changed.

### Integration

An integration test runs on one machine. It may start processes and threads, use files and
localhost services such as PostgreSQL, install signal handlers and arm timers. It cleans up what
it changes: a test that installs a handler restores the previous one, a test that arms a timer
disarms it.

### E2E

An end-to-end test runs an entry point (a CLI, a script, a server) as its own process and checks
it from the outside, through its arguments, output, exit code or network interface.

## Timing

No suite waits a fixed real-time interval or asserts on time in a way a slow machine can break:
short sleeps and sub-second timing make tests flaky on loaded CI machines. A bound on time holds
only in the direction real time can only push it: an elapsed time at least some amount, a time
remaining at most some amount, never an exact value or the other direction. A test waits on an
event or a condition. It polls with a deadline only when nothing can signal, and the deadline is
the failure path, never the expected one. Logic that depends on time runs against a fake clock:
the [`fake_clock` fixture](pytest-plugin.md#fake_clock) of `appinfra.testing`, which only takes
the waiting out. Every test on it passes on the real clock as well.

A unit test runs code that depends on time on the fake clock and asserts what the code does. A
bound on real elapsed time belongs to a test that waits on a real thread, process or timeout,
which is an integration test.

## Assigning a suite

- **Directory**: a test under one of the suite directories above belongs to that suite and needs
  no marker.
- **Override**: the nearest marker wins. A marker on a test overrides its class, a class overrides
  its module, and a module overrides the directory, so a class of unit tests may hold a few tests
  of another suite (`@pytest.mark.integration` on the test).
- **Outside the suite directories** (e.g. `tests/cli/`): every test gets its suite from a marker
  on the test, its class or its module.
- **One suite only**: collection stops on a test with no suite, or with two suite markers on the
  same level.
- **Bound suites**: a project may bind a suite to its directory (`APPINFRA_PYTEST_BOUND_SUITES`,
  e.g. `e2e security performance`). Every test of a bound suite then lives under
  `tests/<suite>/`: the suite's runs collect only that directory, and collection stops on a test
  of the suite found elsewhere, which would otherwise never run.
- **Placement**: a class lives in the directory of the suite most of its tests belong to, and
  module-level tests in the directory of the suite most of their file's tests belong to. A class
  or file of another suite never carries a class- or module-wide marker instead.
- **Overrides**: up to 15% of a class's tests may belong to another suite. Past that they split
  off into a class in their suite's directory. Module-level tests count against every test of
  their file.

The pytest plugin `appinfra.pytest_suites` applies these rules and registers the five suite
markers. A project opts in from its top-level `conftest.py`:

```python
pytest_plugins = ["appinfra.pytest_suites"]
```

The plugin needs the test tooling of the `check` extra (`pip install appinfra[check]`), which
`make setup` installs.

The suite directories are fixed at `tests/<suite>/` under the rootdir, where `make check` also
looks for them. `-m` selects by each test's resolved suite, so `-m unit` leaves out an integration
test in a class marked unit. `make test.unit`, `make test.integration` and `make test.e2e` select
by marker; `make check` runs unit and integration tests together for coverage.

## Test structure health in make check

In a project that loads `appinfra.pytest_suites` and sets `APPINFRA_DEV_TEST_HEALTH` to `warn` or
`strict`, `make check` shows how well the tests keep to these rules, on a Test structure health
line under the test suite:

```
[✓]    Test structure health (98.2%, clean)
[⚠]    Test structure health (95.1%, 2 findings)
```

The percentage is the share of collected tests that keep to the rules: a test outside its
directory's suite, tolerated or not, or a misfiled unit test counts against it. It is for reading,
not judged: the findings decide the line.

Each run of `make check` that executes unit, integration or e2e tests records the figures, and the
line follows the last of them. A class, or a file's module-level tests, may hold up to
`APPINFRA_DEV_TEST_HEALTH_OUTLIERS` (3) tests of other suites whatever its size; a few tests that
need a file or a signal fit in any class. The line looks for structure gone wrong, such as a batch
of integration tests under `tests/unit/`, not for every test out of place. Past that, a finding is
one of:

- **placement**: most of a class's tests belong to another suite; they move to that suite's
  directory, and the rest of the class stays;
- **overrides**: more than `APPINFRA_DEV_TEST_HEALTH_THRESHOLD` (15%) of a class's tests belong to
  another suite; they split off into a class in their suite's directory.

A unit test that left process-wide state changed is a **leak**, a finding of its own: a signal
handler, the `ITIMER_REAL` timer, an environment variable or the working directory, compared from
before its setup to after its teardown. An environment variable a module sets while being
imported is the module's, not the test's.

A unit test seen doing what its suite does not allow is **misfiled**, one finding per class and
target suite, with the first test's evidence:

```
[⚠] Test structure health: tests/unit/test_export.py::TestExport: 3 unit ➜ integration (fs-write /tmp/x)
```

### What a unit test is seen doing

While the unit tests run, an audit hook ([PEP 578](https://peps.python.org/pep-0578/)) and
wrappers around what raises no audit event (`signal.signal`, `signal.setitimer`, the start of a
`multiprocessing` process, shared memory `multiprocessing` allocates, psycopg's connect and
`execute`) record what each test does:

| Evidence | Recorded for | Misfiled to |
|----------|--------------|-------------|
| `fs-write` | a file written, created, removed or renamed; shared memory `multiprocessing` allocates for a `Value`, `Array` or `Barrier`, which lives in a file shared with other processes | integration |
| `fs-read` | a file read outside the project, the interpreter and the system directories | integration |
| `process` | a process started, `multiprocessing` included | integration |
| `socket` | a socket connected or bound | integration |
| `db` | a database connection other than `sqlite3` in memory, a psycopg query | integration |
| `signal` | a signal handler installed or a timer armed | integration |
| `chdir` | the working directory changed | integration |
| `thread` | a thread started, directly or by a thread pool, `run_in_executor` or `asyncio.to_thread` | integration |
| `entry-point` | a process running the project itself: `-m <package>`, a `.py` file of one of its packages, or one of its `[project.scripts]` | e2e |

Not evidence: reading the project's own files, the interpreter's or the system's (`/etc`,
`/proc`, `/usr`, ...), or code anywhere, which is an import; what a tool writes to its cache
(`__pycache__`, `.hypothesis`); writes to a device; `sqlite3` in memory; sleeps; environment
changes, which the leak check covers; and the SIGINT handler `asyncio.run` installs and restores.
Nor is what a module does while being imported, such as making its cache directory: it does that
for whichever test imports it first.

A finding comes only from what a test was seen doing, never from what it was not seen doing.
Integration and e2e tests are not judged: an integration test with no evidence, or an e2e test
that starts the project through a shell script or a container, may be doing work the recording
cannot see. For the same reason some work goes unrecorded and is never a finding:

- the work a thread does once started: only the thread running the test and its fixtures is
  recorded, so a thread an earlier test left running is not charged to the current one. That a
  test started a thread is recorded;
- I/O done in C code that raises no audit event, and database drivers other than `sqlite3` and
  psycopg.

A test is charged with its own work and that of the fixtures it uses: those it asks for (as
arguments or through `usefixtures`), its function-scoped autouse fixtures, and what those depend
on. A fixture wider than one test is charged, setup and teardown, to every test that uses it. An
autouse fixture wider than one test is not charged: it sets up for every test, not for this one.

A unit test whose work belongs to its directory's suite, such as a test marked `unit` under
`tests/integration/` that writes files, counts as that suite for placement and overrides: its
marker is wrong, not its place.

A test that does such work on purpose is exempt from the behavior check, with the reason:

```python
@pytest.mark.suite_exempt(reason="checks the modes the real file system sets")
def test_mode_bits(tmp_path): ...
```

An empty reason stops collection.

The recording runs only while the line is on. Its audit hook and wrappers stay in place for the
rest of each test process, since an audit hook cannot be removed. On appinfra's own suite it adds
1 to 2 seconds to the coverage run of `make check`, about 5%; a suite that runs many psycopg
queries pays more, as each one passes through a wrapper.

### Outcome

The line passes with no finding. Otherwise the findings show under the checklist and in
`.build/check/test-structure-health.log`, and `APPINFRA_DEV_TEST_HEALTH` decides the outcome: `warn`
reports a warning, `strict` fails `make check`; `false` (the default) drops the line. A project
turning the line on with findings to fix starts at `warn` and moves to `strict` once it is clean.

## Rationale

The definitions follow the two most widely used ones:

- **Michael Feathers, "A Set of Unit Testing Rules" (2005).** A test is not a unit test if it talks
  to a database, communicates across a network, touches the file system, "can't run at the same
  time as any of your other unit tests", or needs special environment setup. Process-wide state
  such as signal handlers is excluded by the fourth rule: two tests that install handlers in the
  same process cannot run at the same time.
- **Google's test sizes.** Small tests "must run in a single process"; "in many languages, we
  restrict this even further to say that they must run on a single thread". They "aren't allowed
  to sleep, perform I/O operations, or make any other blocking calls", to keep out "the main
  sources of test slowness or nondeterminism", thread scheduling among them. Medium tests "can
  span multiple processes, use threads, and can make blocking calls", on one machine. `unit`
  corresponds to small, with the single thread, and `integration` to medium.

Martin Fowler takes a looser view: talking to a resource in a unit test is fine if it is stable
and fast enough. These suites follow the stricter definitions because a unit test that shares
process-wide state can make an unrelated later test fail, and a unit run that touches no I/O or
global state stays fast and order-independent.

These suites depart from Google's small tests on sleep. A sleep makes a test slow or flaky, but
not dependent on anything outside it, so the [timing](#timing) rules cover it in every suite
rather than the unit rules alone: moving a sleeping test to the integration suite would not make
it faster or less flaky.

## References

- Michael Feathers, A Set of Unit Testing Rules, Artima, 2005:
  <https://www.artima.com/weblogs/viewpost.jsp?thread=126923>
- Titus Winters, Tom Manshreck, Hyrum Wright (eds.), Software Engineering at Google, ch. 11:
  Testing Overview, O'Reilly, 2020: <https://abseil.io/resources/swe-book/html/ch11.html>
- Test Sizes, Google Testing Blog, 2010: <https://testing.googleblog.com/2010/12/test-sizes.html>
- Martin Fowler, UnitTest: <https://martinfowler.com/bliki/UnitTest.html>
- pytest-run-parallel, runs each test in several threads to find tests that are not parallel-safe:
  <https://pypi.org/project/pytest-run-parallel>, thread-unsafe fixtures discussed in
  <https://github.com/pytest-dev/pytest/issues/13768>
