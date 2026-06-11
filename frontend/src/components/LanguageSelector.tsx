import { LANGS, useI18n } from '../i18n';

export default function LanguageSelector() {
  const { lang, setLang } = useI18n();
  return (
    <div className="lang-selector" role="group" aria-label="Language">
      {LANGS.map(({ code, label }) => (
        <button
          type="button"
          key={code}
          className={lang === code ? 'on' : ''}
          onClick={() => setLang(code)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
