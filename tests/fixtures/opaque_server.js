// Reference OPAQUE server using @serenity-kit/opaque (same lib/version as dcli).
// Protocol on stdio: line1 out = JSON {setupPk}, then reads python's start request,
// answers loginResponse, reads finish request, prints session key.
const opaque = require('@serenity-kit/opaque');
const readline = require('readline');
(async () => {
  await opaque.ready;
  const password = process.argv[2];
  const loginPassword = process.argv[3] || password;
  const ids = { server: 'api.dashlane.com' };
  const ks = { 'argon2id-custom': { iterations: 3, memory: 65536, parallelism: 4 } };
  const serverSetup = opaque.server.createSetup();
  const { clientRegistrationState, registrationRequest } = opaque.client.startRegistration({ password });
  const { registrationResponse } = opaque.server.createRegistrationResponse({ serverSetup, userIdentifier: 'u', registrationRequest });
  const reg = opaque.client.finishRegistration({ clientRegistrationState, registrationResponse, password, identifiers: ids, keyStretching: ks });
  const rl = readline.createInterface({ input: process.stdin });
  const it = rl[Symbol.asyncIterator]();
  console.log(JSON.stringify({ serverStaticPublicKey: reg.serverStaticPublicKey, exportKey: reg.exportKey }));
  const startLoginRequest = (await it.next()).value.trim();
  const { serverLoginState, loginResponse } = opaque.server.startLogin({ serverSetup, registrationRecord: reg.registrationRecord, startLoginRequest, userIdentifier: 'u', identifiers: ids });
  console.log(loginResponse);
  const finishLoginRequest = (await it.next()).value.trim();
  try {
    const { sessionKey } = opaque.server.finishLogin({ serverLoginState, finishLoginRequest, identifiers: ids });
    console.log(JSON.stringify({ sessionKey }));
  } catch (e) { console.log(JSON.stringify({ error: String(e) })); }
  // also: does the JS client agree with itself (sanity)?
  rl.close();
})();
