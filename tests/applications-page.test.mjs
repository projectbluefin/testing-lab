import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const repo = process.cwd();

function html(file) {
  return readFileSync(path.join(repo, file), 'utf8');
}

test('applications page renders Bazaar evidence, chart mounts, and explicit unavailable states', () => {
  execFileSync('npm', ['run', 'build'], {
    cwd: repo,
    stdio: 'pipe',
    encoding: 'utf8',
  });

  const applicationsPage = html('docs/applications/index.html');

  assert.match(
    applicationsPage,
    /No completed application-specific software result is published/i,
    'applications page keeps unavailable primary evidence explicit',
  );
  assert.match(
    applicationsPage,
    /Firefox/i,
    'applications page includes Firefox as a tracked application',
  );
  assert.match(
    applicationsPage,
    /Ptyxis/i,
    'applications page includes Ptyxis terminal emulator',
  );
  assert.match(
    applicationsPage,
    /Podman Desktop/i,
    'applications page includes Podman Desktop container GUI',
  );
  assert.match(
    applicationsPage,
    /behave tests\/developer\/features\/ptyxis\.feature/i,
    'applications page renders awesome behave terminal execution snippets',
  );
  assert.match(
    applicationsPage,
    /View on GitHub/i,
    'applications page links behave test suites directly to GitHub',
  );
  assert.match(
    applicationsPage,
    /Architectures/i,
    'applications page displays architectures metadata',
  );
  assert.match(
    applicationsPage,
    /License/i,
    'applications page displays license metadata',
  );
  assert.match(
    applicationsPage,
    /Flatpak SDK Runtime/i,
    'applications page displays Flatpak SDK runtime metadata',
  );
  assert.match(
    applicationsPage,
    /applications-outcomes-chart/,
    'applications page renders the outcomes chart container',
  );
  assert.match(
    applicationsPage,
    /applications-fallback-chart/,
    'applications page renders the fallback distribution chart container',
  );
  assert.match(
    applicationsPage,
    /applications-history-chart/,
    'applications page renders the evidence history chart container',
  );
  assert.match(
    applicationsPage,
    /applications-page-data/,
    'applications page serializes client chart data',
  );
  assert.match(
    applicationsPage,
    /https:\/\/github\.com\/projectbluefin\/testing-lab\/blob\/main\/docs\/results\/bluefin-testing-common\.json/,
    'applications page links fallback evidence',
  );
});
