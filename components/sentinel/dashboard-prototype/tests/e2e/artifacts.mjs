import {mkdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';

/** Each named suite writes only within the caller's run directory; never delete an external baseline. */
export function artifactDirectory(name, parent = process.env.SENTINEL_TEST_ARTIFACT_DIR ?? tmpdir()) {
  if (!/^[a-z0-9][a-z0-9-]{0,100}$/.test(name)) throw new Error('Invalid artifact suite name');
  const directory = join(resolve(parent),name);
  mkdirSync(directory,{recursive:true});
  return directory;
}
