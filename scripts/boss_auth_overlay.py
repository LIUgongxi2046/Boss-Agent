def apply_auth_overlay(source, replace):
    source = replace(source, 'export default function App() {\n  const { t } = useTranslation();', 'export default function App() {', 'application authentication translations')
    source = replace(source, 'function AuthForm({', 'export function NativeAuthForm({', 'native authentication export')
    source = replace(source, '  fetchBootstrap,\n', '', 'bootstrap import')
    source = replace(source, '  clearSavedSecret,\n', '', 'logout import')
    source = replace(source, 'import { BossDesktop } from "./boss-agent/BossDesktop";',
                     'import { BossDesktop } from "./boss-agent/BossDesktop";\n'
                     'import { BossLogin, bossFetchBootstrap as fetchBootstrap, bossClearSavedSecret as clearSavedSecret } from "./boss-agent/BossLogin";',
                     'branded authentication import')
    source = replace(source, '| { status: "auth"; failed?: boolean }', '| { status: "auth"; failed?: boolean; expired?: boolean }', 'expired authentication state')
    source = replace(source, '''      <AuthForm
        failed={!!state.failed}
        onSecret={(s) => bootstrapWithSecret(s)}
      />''', '''      <BossLogin
        failed={!!state.failed} expired={!!state.expired}
        onSecret={(s) => bootstrapWithSecret(s)}
      />''', 'authentication form')
    source = replace(source, '''      <div className="flex h-full w-full items-center justify-center">
        <div className="flex flex-col items-center gap-3 animate-in fade-in-0 duration-300">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-foreground/40" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-foreground/60" />
            </span>
            {t("app.loading.connecting")}
          </div>
        </div>
      </div>''', '''      <BossLogin mode="loading" onSecret={(s) => bootstrapWithSecret(s)} />''', 'authentication loading')
    source = replace(source, '''      <div className="flex h-full w-full items-center justify-center px-4 text-center">
        <div className="flex max-w-md flex-col items-center gap-3">
          <p className="text-lg font-semibold">{t("app.error.title")}</p>
          <p className="text-sm text-muted-foreground">{state.message}</p>
          <p className="text-xs text-muted-foreground">
            {t("app.error.gatewayHint")}
          </p>
        </div>
      </div>''', '''      <BossLogin mode="error" message={state.message} onSecret={(s) => bootstrapWithSecret(s)} />''', 'authentication service error')
    source = replace(source, '''  const handleLogout = () => {
    if (state.status === "ready") {
      state.client.close();
    }
    clearSavedSecret();
    setState({ status: "auth" });
  };''', '''  const handleLogout = async () => {
    if (state.status !== "ready") return;
    try {
      await state.client.requestMutation("boss.auth.logout", {});
    } finally {
      state.client.close();
      bootstrapSecretRef.current = "";
      clearSavedSecret();
      setState({ status: "auth" });
    }
  };''', 'authenticated logout')
    source = replace(source, '''              } catch {
                return null;
              }
            },''', '''              } catch {
                client.close();
                clearSavedSecret();
                setState({ status: "auth", expired: true });
                return null;
              }
            },''', 'websocket authentication expiry')
    source = replace(source, '''          setState({ status: "auth", failed: !!bootstrapSecretRef.current });''', '''          client.close();
          clearSavedSecret();
          bootstrapSecretRef.current = "";
          setState({ status: "auth", expired: true });''', 'refresh authentication expiry')
    source = replace(source, '''  const bootstrapSecretRef = useRef("");''', '''  const bootstrapSecretRef = useRef("");
  useEffect(() => {
    if (state.status !== "ready") return;
    const expire = () => {
      state.client.close();
      bootstrapSecretRef.current = "";
      clearSavedSecret();
      setState({ status: "auth", expired: true });
    };
    window.addEventListener("boss-auth-expired", expire);
    return () => window.removeEventListener("boss-auth-expired", expire);
  }, [state]);''', 'protected content expiry')
    return source
