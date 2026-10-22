import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Mic, Square, Send, Trash2, Loader2 } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

const MAX_DURATION_MS = 60_000;
const MAX_AUDIO_BYTES = 3_000_000;

type Stage = "idle" | "recording" | "recorded" | "transcribing" | "review" | "sending";
type Props = {
  getToken: () => string;
  onSubmit: (content: string) => Promise<boolean | void>;
  onOpenConversation: () => void;
};

type DesktopBridge = {
  invoke: (args: { action: string; token: string }) => Promise<unknown>;
};
function supportedMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  return ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"]
    .find(type => MediaRecorder.isTypeSupported(type)) || "";
}
function toDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => typeof reader.result === "string"
      ? resolve(reader.result) : reject(new Error("音频内容读取失败"));
    reader.onerror = () => reject(new Error("音频内容读取失败"));
    reader.readAsDataURL(blob);
  });
}

export function BossVoiceAssignment({ getToken, onSubmit, onOpenConversation }: Props) {
  const { client } = useClient();
  const [stage, setStage] = useState<Stage>("idle");
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [audio, setAudio] = useState<Blob | null>(null);
  const [audioUrl, setAudioUrl] = useState("");
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const stopTimerRef = useRef<number | null>(null);
  const tickerRef = useRef<number | null>(null);
  const startRef = useRef(0);
  const mountedRef = useRef(true);

  const releaseMic = () => {
    if (stopTimerRef.current !== null) window.clearTimeout(stopTimerRef.current);
    if (tickerRef.current !== null) window.clearInterval(tickerRef.current);
    stopTimerRef.current = null;
    tickerRef.current = null;
    streamRef.current?.getTracks().forEach(track => track.stop());
    streamRef.current = null;
  };
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      releaseMic();
    };
  }, []);
  useEffect(() => {
    return () => { if (audioUrl) URL.revokeObjectURL(audioUrl); };
  }, [audioUrl]);

  const reset = () => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    releaseMic();
    recorderRef.current = null;
    setAudio(null);
    setAudioUrl("");
    setElapsed(0);
    setDraft("");
    setNotice("");
    setError("");
    setStage("idle");
  };

  const stopRecording = () => {
    const recorder = recorderRef.current;
    if (recorder?.state === "recording") recorder.stop();
    releaseMic();
  };

  const startRecording = async () => {
    if (stage !== "idle" && stage !== "recorded") return;
    setError("");
    setNotice("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("当前设备不支持麦克风录音；可改用原生文本交办。");
      return;
    }
    try {
      const bridge = (window as Window & { bossDesktop?: DesktopBridge }).bossDesktop;
      if (bridge) {
        const granted = await bridge.invoke({ action: "request_microphone", token: getToken() });
        if (granted !== true) throw new Error("尚未取得 macOS 麦克风授权");
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mountedRef.current) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      streamRef.current = stream;
      const mime = supportedMime();
      const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      chunksRef.current = [];
      recorderRef.current = recorder;
      recorder.ondataavailable = event => { if (event.data.size > 0) chunksRef.current.push(event.data); };
      recorder.onerror = () => {
        releaseMic();
        if (mountedRef.current) {
          setStage("idle");
          setError("录音设备出现错误，请重新录制。");
        }
      };
      recorder.onstop = () => {
        releaseMic();
        if (!mountedRef.current) return;
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        chunksRef.current = [];
        if (!blob.size || blob.size > MAX_AUDIO_BYTES) {
          setStage("idle");
          setAudio(null);
          setError(blob.size > MAX_AUDIO_BYTES ? "录音文件超过 3MB，请缩短时长。" : "没有检测到有效录音。");
          return;
        }
        setAudio(blob);
        setAudioUrl(URL.createObjectURL(blob));
        setStage("recorded");
      };
      recorder.start(300);
      startRef.current = Date.now();
      setElapsed(0);
      setStage("recording");
      tickerRef.current = window.setInterval(() => {
        if (mountedRef.current) setElapsed(Math.min(60, Math.floor((Date.now() - startRef.current) / 1000)));
      }, 250);
      stopTimerRef.current = window.setTimeout(stopRecording, MAX_DURATION_MS);
    } catch (err) {
      releaseMic();
      setStage("idle");
      setError(err instanceof Error && /麦克风授权/.test(err.message)
        ? err.message : "无法启动录音，请检查系统权限和设备。");
    }
  };

  const transcribe = async () => {
    if (!audio || stage !== "recorded") return;
    setStage("transcribing");
    setError("");
    try {
      if (audio.size > MAX_AUDIO_BYTES) throw new Error("录音超出限制");
      const text = await client.transcribeAudio(await toDataUrl(audio), {
        durationMs: Math.min(elapsed * 1000, MAX_DURATION_MS),
        timeoutMs: 120_000,
      });
      if (!mountedRef.current) return;
      if (!text.trim()) throw new Error("转写没有返回有效文字");
      setDraft(text.trim());
      setStage("review");
      setNotice("已收到语音转写结果。请先核对、修改文字，再明确提交。");
    } catch {
      if (!mountedRef.current) return;
      setStage("recorded");
      setError("当前语音转写服务不可用或请求失败。录音没有发送为 Agent 指令；请核查服务配置后重试。");
    }
  };

  const send = async () => {
    if (stage !== "review" || !draft.trim()) {
      setError("转写文本为空，请确认后再提交。");
      return;
    }
    setStage("sending");
    setError("");
    try {
      const accepted = await onSubmit(draft.trim());
      if (accepted === false) throw new Error("会话未能创建");
      if (!mountedRef.current) return;
      setAudio(null);
      setAudioUrl("");
      setDraft("");
      setNotice("");
      onOpenConversation();
    } catch {
      if (!mountedRef.current) return;
      setStage("review");
      setError("未能提交已核对的文字；草稿已保留，可重试。");
    }
  };

  return <div className="boss-columns">
    <div className="boss-column">
      <section className="boss-panel">
        <div className="boss-panel-head"><h2>大鹏 · 语音交办</h2><small>F27 · 本地录音与逐项确认</small></div>
        <p className="boss-helper">录音须由老板主动开始，最长 60 秒、3MB。录音完成后才会向当前 nanobot 转写服务发送音频。转写内容必须经本人核对后才能提交为 Agent 需求。</p>
        <div className="boss-actions">
          {stage === "idle" || stage === "recorded" ?
            <button type="button" className="boss-btn boss-btn-primary" onClick={() => void startRecording()}>
              <Mic size={16}/> {stage === "recorded" ? "重新录音" : "开始录音"}
            </button> : null}
          {stage === "recording" ?
            <button type="button" className="boss-btn boss-btn-primary" onClick={stopRecording}>
              <Square size={15}/> 结束录音（{elapsed} 秒）
            </button> : null}
          {stage === "recorded" ?
            <button type="button" className="boss-btn" onClick={() => void transcribe()}>
              <Mic size={16}/> 提交转写（需服务已启用）
            </button> : null}
          {stage === "transcribing" ? <span role="status"><Loader2 className="boss-spin" size={16}/> 正在等待转写服务…</span> : null}
          <button type="button" className="boss-btn" onClick={reset} disabled={stage === "transcribing" || stage === "sending"}>
            <Trash2 size={15}/> 清除录音与草稿
          </button>
        </div>
        {audioUrl && stage !== "recording" ? <audio className="boss-voice-player" controls src={audioUrl} aria-label="回放本人录音"/> : null}
        {error ? <div className="boss-status boss-status-error" role="alert"><AlertCircle size={16}/>{error}</div> : null}
        {notice ? <div className="boss-status boss-status-ok" role="status"><CheckCircle2 size={16}/>{notice}</div> : null}
      </section>
      <section className="boss-panel">
        <div className="boss-panel-head"><h2>本人核对的交办内容</h2><small>必须确认后发送</small></div>
        <label className="boss-label" htmlFor="boss-voice-draft">转写文本（可修改）</label>
        <textarea id="boss-voice-draft" rows={6} disabled={stage !== "review"} value={draft}
          onChange={e => setDraft(e.target.value)}
          placeholder="录音转写成功后在这里核对、纠正姓名、期限和业务对象。"/>
        <div className="boss-actions">
          <button type="button" className="boss-btn boss-btn-primary" disabled={stage !== "review" || !draft.trim()}
            onClick={() => void send()}><Send size={16}/> 确认文字并进入 Agent 会话</button>
        </div>
      </section>
    </div>
    <div className="boss-column">
      <section className="boss-panel">
        <div className="boss-panel-head"><h2>执行状态与隐私</h2><small>已认证 BOSS 专用</small></div>
        <div className="boss-kv"><span>录音状态</span><strong>{stage}</strong></div>
        <div className="boss-kv"><span>实际转写</span><strong>{stage === "review" || stage === "sending" ? "已取得文字，待本人提交" : "尚未成功转写"}</strong></div>
        <div className="boss-kv"><span>数据范围</span><strong>本机录制 · 明确请求才转写</strong></div>
        <div className="boss-status boss-status-warn">
          <AlertCircle size={16}/> 当前固定开发配置默认关闭语音转写。启用真实转写服务及 macOS 权限联调前，不会把录音伪装为已识别或已交办。
        </div>
        <div className="boss-actions">
          <button type="button" className="boss-btn" onClick={onOpenConversation}>转至文本交办</button>
        </div>
      </section>
    </div>
  </div>;
}
