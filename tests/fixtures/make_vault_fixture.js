// Builds encrypted Dashlane-format transactions (same format as dashlane-cli
// src/modules/crypto) to test the Python decryptor against Node's crypto.
//   npm install @node-rs/argon2 && node make_vault_fixture.js > vault_fixture.json
const crypto = require('crypto');
const zlib = require('zlib');
const argon2 = require('@node-rs/argon2');

const PASSWORD = 'Tr0ub4dor & "3" ✓';

const xml = (kind, fields) =>
  '<?xml version="1.0" encoding="UTF-8"?><root><' + kind + '>' +
  Object.entries(fields).map(([k, v]) => '<KWDataItem key="' + k + '"><![CDATA[' + v + ']]></KWDataItem>').join('') +
  '<KWDataItem key="Note"><![CDATA[ignored]]></KWDataItem></' + kind + '></root>';

const pack = (text) => {
  const deflated = zlib.deflateRawSync(Buffer.from(text));
  const head = Buffer.alloc(6);
  head.writeUInt32BE(deflated.length, 0);
  head[4] = 0x78;
  head[5] = 0x9c;
  return Buffer.concat([head, deflated]);
};

const encrypt = (plain, kdf, salt, key) => {
  const combined = crypto.createHash('sha512').update(key).digest();
  const iv = crypto.randomBytes(16);
  const c = crypto.createCipheriv('aes-256-cbc', combined.slice(0, 32), iv);
  const ct = Buffer.concat([c.update(plain), c.final()]);
  const mac = crypto.createHmac('sha256', combined.slice(32)).update(Buffer.concat([iv, ct])).digest();
  const header = Buffer.from('$1$' + kdf + '$aes256$cbchmac$16$', 'ascii');
  return Buffer.concat([header, salt, iv, mac, ct]).toString('base64');
};

(async () => {
  const saltA = crypto.randomBytes(16);
  const saltB = crypto.randomBytes(16);
  const saltP = crypto.randomBytes(16);
  const argonKey = (salt) => argon2.hashRaw(PASSWORD, {
    algorithm: 0, timeCost: 3, memoryCost: 32768, parallelism: 2, salt, version: 1, outputLen: 32,
  });
  const keyA = await argonKey(saltA);
  const keyB = await argonKey(saltB);
  const keyP = crypto.pbkdf2Sync(PASSWORD, saltP, 10000, 32, 'sha256');
  const A = (p) => encrypt(p, 'argon2d$16$3$32768$2', saltA, keyA);
  const B = (p) => encrypt(p, 'argon2d$16$3$32768$2', saltB, keyB);
  const Pk = (p) => encrypt(p, 'pbkdf2$16$10000$sha256', saltP, keyP);
  const tr = (identifier, type, content) => ({ backupDate: 1, identifier, time: 1, content, type, action: 'BACKUP_EDIT' });
  const first = [
    tr('SETTINGS_userId', 'SETTINGS', A(pack(xml('KWSettingsManagerApp', { Format: 'x' })))),
    tr('{11111111-1111-1111-1111-111111111111}', 'AUTHENTIFIANT', A(pack(xml('KWAuthentifiant', {
      Id: '{11111111-1111-1111-1111-111111111111}', Title: 'GitHub', Url: 'https://github.com/login',
      Login: 'octocat', Email: 'octo@example.com', Password: 'p@ss "quoted" \\ back',
      OtpSecret: 'JBSWY3DPEHPK3PXP',
    })))),
    tr('{22222222-2222-2222-2222-222222222222}', 'AUTHENTIFIANT', B(pack(xml('KWAuthentifiant', {
      Id: '{22222222-2222-2222-2222-222222222222}', Title: 'Émile & Co', Url: 'shop.example.co.uk',
      Login: 'emile', Password: 'ünïcødé-пароль',
    })))),
    tr('{33333333-3333-3333-3333-333333333333}', 'AUTHENTIFIANT', Pk(pack(xml('KWAuthentifiant', {
      Id: '{33333333-3333-3333-3333-333333333333}', Title: '', Url: 'https://mail.google.com',
      Email: 'someone@gmail.com', Password: 'legacy-pbkdf2',
      OtpUrl: 'otpauth://totp/Google:someone?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&algorithm=SHA256&digits=8&period=60',
    })))),
    tr('{44444444-4444-4444-4444-444444444444}', 'SECURENOTE', A(pack(xml('KWSecureNote', { Title: 'not a credential' })))),
  ];
  const second = [
    tr('{11111111-1111-1111-1111-111111111111}', 'AUTHENTIFIANT', B(pack(xml('KWAuthentifiant', {
      Id: '{11111111-1111-1111-1111-111111111111}', Title: 'GitHub', Url: 'https://github.com/login',
      Login: 'octocat', Email: 'octo@example.com', Password: 'rotated-password', OtpSecret: 'JBSWY3DPEHPK3PXP',
    })))),
    { backupDate: 2, identifier: '{22222222-2222-2222-2222-222222222222}', time: 2, type: 'AUTHENTIFIANT', action: 'BACKUP_REMOVE' },
  ];
  console.log(JSON.stringify({ password: PASSWORD, first, second }, null, 1));
})();
