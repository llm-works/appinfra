# Test Suites

Every test belongs to exactly one suite. The suite is decided by what the test touches, not by
what it is about: a test of pure parsing logic that writes its input to a temporary file is an
integration test.

## Definitions

| Suite | Runs in | May touch | Directory |
|-------|---------|-----------|-----------|
| `unit` | one process | memory only | `tests/unit/` |
| `integration` | one machine | processes, files, localhost services, databases, signals, timers | `tests/integration/` |
| `e2e` | one machine | an entry point started as its own process | `tests/e2e/` |
| `security` | by purpose | security behaviour (injection, validation) | `tests/security/` |
| `performance` | by purpose | benchmarks | `tests/performance/` |

### Unit

A unit test stays in one process and, in principle, could run at the same time as any other unit
test in that process. The rules below follow from that: a test that does I/O, blocks, or touches
process-wide state depends on something outside its control or changes what another test sees. A
unit test must not:

- **perform I/O**: files (`tmp_path` included), sockets, subprocesses, databases, file watchers;
- **block**: sleep, wait on real time, or wait on another thread or process;
- **use or change process-wide state that outlives the test**: signal handlers, interval timers
  (`setitimer`, `alarm`).

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

No suite asserts on elapsed time or waits a fixed real-time interval: short sleeps and
sub-second timing make tests flaky on loaded CI machines. A test waits on an event or a
condition. It polls with a deadline only when nothing can signal, and the deadline is the failure
path, never the expected one. Logic that depends on time runs against a fake clock.

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

The percentage is the share of tests that run in their directory's suite; the tests the rules
tolerate elsewhere count against it. It is for reading, not judged: the findings decide the line.

The run that executes the unit tests records the figures, and the line follows it. A class, or a
file's module-level tests, may hold up to `APPINFRA_DEV_TEST_HEALTH_OUTLIERS` (3) tests of other
suites whatever its size; a few tests that need a file or a signal fit in any class. The line
looks for structure gone wrong, such as a batch of integration tests under `tests/unit/`, not
for every test out of place. Past that, a finding is one of:

- **placement**: most of a class's tests belong to another suite; they move to that suite's
  directory, and the rest of the class stays;
- **overrides**: more than `APPINFRA_DEV_TEST_HEALTH_THRESHOLD` (15%) of a class's tests belong to
  another suite; they split off into a class in their suite's directory.

A unit test that left process-wide state changed is a **leak**, a finding of its own: a signal
handler, the `ITIMER_REAL` timer, an environment variable or the working directory, compared from
before its setup to after its teardown. An environment variable a module sets while being
imported, as torch or vllm do on first import, is not the test's.

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
- **Google's test sizes.** Small tests "must run in a single process", often a single thread, and
  "aren't allowed to sleep, perform I/O operations, or make any other blocking calls", to keep out
  "the main sources of test slowness or nondeterminism". Medium tests may span processes on one
  machine and call localhost. `unit` corresponds to small, `integration` to medium.

Martin Fowler takes a looser view: talking to a resource in a unit test is fine if it is stable
and fast enough. These suites follow the stricter definitions because a unit test that shares
process-wide state can make an unrelated later test fail, and a unit run that touches no I/O or
global state stays fast and order-independent.

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
