import { useEffect, useRef, useState, type ReactNode } from "react";
import type * as Three from "three";
import type { VRM } from "@pixiv/three-vrm";
import {
  formatVrmMetaSummary,
  inspectVrmBinary,
  summarizeVrmMeta,
  validateVrmFile,
  vrmEmotionForCompanionState,
  type VrmEmotion,
  type VrmMetaSummary,
} from "../lib/vrm";

export type VrmAvatarStatus = "idle" | "loading" | "ready" | "error";

export interface VRMAvatarProps {
  /** Conversation state used for idle motion, expression and mouth animation. */
  state: string;
  /** Optional explicit VRM expression; otherwise it is derived from state. */
  expression?: VrmEmotion;
  /** Rendered while no user model is loaded or when WebGL/VRM loading fails. */
  fallback: ReactNode;
  /** Compact mode is used in the companion portrait column. */
  compact?: boolean;
  onMeta?(meta: VrmMetaSummary | null): void;
  onStatus?(status: VrmAvatarStatus, message?: string): void;
}

interface AvatarRuntime {
  renderer: Three.WebGLRenderer;
  scene: Three.Scene;
  camera: Three.PerspectiveCamera;
  vrm: VRM;
  target: Three.Object3D;
  frame: number;
  resizeObserver?: ResizeObserver;
  removePointer?: () => void;
  renderStatic(): void;
  dispose(): void;
}

const MAX_PIXEL_RATIO = 2;

const safeErrorMessage = (error: unknown): string => {
  // Do not expose local paths, parser internals or object URLs in the UI.
  const message = error instanceof Error ? error.message : "";
  if (/webgl|context|gpu/i.test(message)) return "当前浏览器无法创建 WebGL 画布，已保留静态立绘。";
  if (/parse|gltf|vrm|buffer|invalid/i.test(message)) return "VRM 文件无法解析，请确认它是有效的 VRM 0.x/1.0 文件。";
  return "VRM 加载失败，已保留静态立绘。";
};

const disposeMaterial = (material: Three.Material | Three.Material[]) => {
  const materials = Array.isArray(material) ? material : [material];
  for (const item of materials) {
    for (const value of Object.values(item)) {
      if (value && typeof value === "object" && "dispose" in value && typeof value.dispose === "function") {
        (value as { dispose(): void }).dispose();
      }
    }
    item.dispose();
  }
};

const disposeObjectTree = (root: Three.Object3D) => {
  root.traverse((object) => {
    const mesh = object as Three.Mesh;
    if (mesh.geometry && typeof mesh.geometry.dispose === "function") mesh.geometry.dispose();
    const material = mesh.material;
    if (material) disposeMaterial(material);
  });
};

/**
 * A local-only VRM viewer. Three.js and the VRM loader are imported inside the
 * effect so the default portrait path does not pay the runtime's initial cost.
 */
export const VRMAvatar = ({
  state,
  expression,
  fallback,
  compact = false,
  onMeta,
  onStatus,
}: VRMAvatarProps) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const stateRef = useRef(state);
  const expressionRef = useRef(expression);
  const onMetaRef = useRef(onMeta);
  const onStatusRef = useRef(onStatus);
  const consentRef = useRef(false);
  const loadRequestRef = useRef(0);
  const mountedRef = useRef(false);
  const renderStaticRef = useRef<(() => void) | null>(null);
  const [consent, setConsent] = useState(false);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [status, setStatus] = useState<VrmAvatarStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<VrmMetaSummary | null>(null);

  stateRef.current = state;
  expressionRef.current = expression;
  onMetaRef.current = onMeta;
  onStatusRef.current = onStatus;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      loadRequestRef.current += 1;
      renderStaticRef.current = null;
    };
  }, []);

  useEffect(() => {
    renderStaticRef.current?.();
  }, [state, expression]);

  const reportStatus = (next: VrmAvatarStatus, message?: string) => {
    if (!mountedRef.current) return;
    setStatus(next);
    onStatusRef.current?.(next, message);
  };

  const clearModel = () => {
    loadRequestRef.current += 1;
    setObjectUrl(null);
    setFileName(null);
    setMeta(null);
    setError(null);
    reportStatus("idle");
    onMetaRef.current?.(null);
  };

  useEffect(() => {
    if (!objectUrl || !canvasRef.current) return;
    let cancelled = false;
    let runtime: AvatarRuntime | null = null;
    let provisionalRenderer: Three.WebGLRenderer | null = null;
    let provisionalVrm: VRM | null = null;

    const load = async () => {
      reportStatus("loading");
      setError(null);
      try {
        // Explicit literals keep these imports in a separate Vite chunk.
        const [THREE, loaderModule, vrmModule] = await Promise.all([
          import("three"),
          import("three/examples/jsm/loaders/GLTFLoader.js"),
          import("@pixiv/three-vrm"),
        ]);
        if (cancelled || !canvasRef.current) return;

        const renderer = new THREE.WebGLRenderer({
          canvas: canvasRef.current,
          alpha: true,
          antialias: true,
          powerPreference: "low-power",
        });
        provisionalRenderer = renderer;
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO));
        renderer.setClearColor(0x000000, 0);
        // three r180 exposes outputColorSpace; keep this guard for older WebGL implementations.
        if ("outputColorSpace" in renderer) renderer.outputColorSpace = THREE.SRGBColorSpace;

        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100);
        scene.add(new THREE.HemisphereLight(0xc9fff7, 0x15241f, 1.4));
        const key = new THREE.DirectionalLight(0xffffff, 2.2);
        key.position.set(1.5, 2.5, 3);
        scene.add(key);
        const fill = new THREE.DirectionalLight(0x8ee8ff, 0.75);
        fill.position.set(-2, 1, 1);
        scene.add(fill);

        const loader = new loaderModule.GLTFLoader();
        loader.register((parser) => new vrmModule.VRMLoaderPlugin(parser));
        const gltf = await loader.loadAsync(objectUrl);
        const vrm = gltf.userData.vrm as VRM | undefined;
        if (!vrm) throw new Error("VRM extension missing");
        provisionalVrm = vrm;
        if (cancelled) {
          vrmModule.VRMUtils.deepDispose(vrm.scene);
          renderer.dispose();
          provisionalVrm = null;
          provisionalRenderer = null;
          return;
        }

        // VRM 0.x and 1.0 use different forward-axis conventions.  The
        // official helper rotates only legacy 0.x models and leaves 1.0
        // models untouched.
        vrmModule.VRMUtils.rotateVRM0(vrm);
        scene.add(vrm.scene);

        const bounds = new THREE.Box3().setFromObject(vrm.scene);
        const size = bounds.getSize(new THREE.Vector3());
        const center = bounds.getCenter(new THREE.Vector3());
        const maxDimension = Math.max(size.x, size.y, size.z, 0.1);
        const distance = (maxDimension / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2))) * 1.18;
        camera.position.set(center.x, center.y + size.y * 0.04, center.z + distance);
        camera.near = Math.max(maxDimension / 100, 0.01);
        camera.far = Math.max(maxDimension * 100, 10);
        camera.lookAt(center.x, center.y + size.y * 0.03, center.z);
        camera.updateProjectionMatrix();

        const target = new THREE.Object3D();
        target.position.set(center.x, center.y + size.y * 0.1, center.z + distance);
        scene.add(target);
        if (vrm.lookAt) {
          vrm.lookAt.target = target;
          vrm.lookAt.autoUpdate = true;
        }

        const resize = () => {
          if (!canvasRef.current) return;
          const width = Math.max(canvasRef.current.clientWidth, 240);
          const height = Math.max(canvasRef.current.clientHeight, 240);
          renderer.setSize(width, height, false);
          camera.aspect = width / height;
          camera.updateProjectionMatrix();
        };
        resize();
        const resizeObserver = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(resize);
        resizeObserver?.observe(canvasRef.current);

        const pointerMove = (event: PointerEvent) => {
          if (!canvasRef.current) return;
          const rect = canvasRef.current.getBoundingClientRect();
          const x = rect.width > 0 ? ((event.clientX - rect.left) / rect.width) * 2 - 1 : 0;
          const y = rect.height > 0 ? ((event.clientY - rect.top) / rect.height) * 2 - 1 : 0;
          target.position.set(center.x + x * size.x * 0.32, center.y - y * size.y * 0.2, center.z + distance);
        };
        canvasRef.current.addEventListener("pointermove", pointerMove, { passive: true });

        const motionQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)");
        let previous = performance.now();
        let running = false;
        let blinkTimer = 1.5 + Math.random() * 2;
        let blinkProgress = -1;
        const head = vrm.humanoid.getNormalizedBoneNode("head");
        const neck = vrm.humanoid.getNormalizedBoneNode("neck");
        const headBase = head?.rotation.clone();
        const neckBase = neck?.rotation.clone();
        const expressionNames = ["neutral", "happy", "sad", "angry", "relaxed", "surprised"] as const;
        const renderFrame = (now: number, delta: number, animate: boolean) => {
          const elapsed = now / 1000;
          const currentState = stateRef.current;
          const currentEmotion = expressionRef.current ?? vrmEmotionForCompanionState(currentState);

          if (head && headBase) {
            head.rotation.x = headBase.x + (animate ? Math.sin(elapsed * 0.8) * 0.012 : 0);
            head.rotation.z = headBase.z + (animate ? Math.sin(elapsed * 0.55) * 0.009 : 0);
          }
          if (neck && neckBase) neck.rotation.y = neckBase.y + (animate ? Math.sin(elapsed * 0.42) * 0.018 : 0);

          const manager = vrm.expressionManager;
          if (manager) {
            for (const name of expressionNames) manager.setValue(name, name === currentEmotion ? 0.72 : 0);
            if (animate) {
              blinkTimer -= delta;
              if (blinkProgress < 0 && blinkTimer <= 0) blinkProgress = 0;
              if (blinkProgress >= 0) {
                blinkProgress += delta / 0.16;
                const blink = blinkProgress < 0.5 ? blinkProgress * 2 : (1 - blinkProgress) * 2;
                manager.setValue("blink", Math.max(0, Math.min(1, blink)));
                if (blinkProgress >= 1) {
                  blinkProgress = -1;
                  blinkTimer = 2.2 + Math.random() * 4.5;
                }
              } else {
                manager.setValue("blink", 0);
              }
            } else {
              manager.setValue("blink", 0);
            }
            const speaking = currentState === "speaking";
            manager.setValue("aa", speaking && animate ? 0.2 + (Math.sin(elapsed * 12) + 1) * 0.18 : 0);
          }
          vrm.update(animate ? delta : 0);
          renderer.render(scene, camera);
        };

        const loop = (now: number) => {
          if (cancelled || !running) return;
          const delta = Math.min((now - previous) / 1000, 0.1);
          previous = now;
          renderFrame(now, delta, true);
          runtime!.frame = requestAnimationFrame(loop);
        };

        const syncMotion = () => {
          if (cancelled || !runtime) return;
          const shouldRun = !(motionQuery?.matches ?? false) && document.visibilityState !== "hidden";
          if (shouldRun && !running) {
            running = true;
            previous = performance.now();
            runtime.frame = requestAnimationFrame(loop);
          } else if (!shouldRun) {
            if (running) cancelAnimationFrame(runtime.frame);
            running = false;
            if (document.visibilityState !== "hidden") renderFrame(performance.now(), 0, false);
          }
        };

        runtime = {
          renderer,
          scene,
          camera,
          vrm,
          target,
          frame: 0,
          resizeObserver,
          removePointer: () => canvasRef.current?.removeEventListener("pointermove", pointerMove),
          renderStatic: () => {
            if (document.visibilityState !== "hidden") renderFrame(performance.now(), 0, false);
          },
          dispose: () => {
            running = false;
            cancelAnimationFrame(runtime?.frame ?? 0);
            resizeObserver?.disconnect();
            canvasRef.current?.removeEventListener("pointermove", pointerMove);
            motionQuery?.removeEventListener?.("change", syncMotion);
            document.removeEventListener("visibilitychange", syncMotion);
            vrmModule.VRMUtils.deepDispose(vrm.scene);
            renderer.dispose();
            renderer.forceContextLoss?.();
            scene.clear();
          },
        };
        renderStaticRef.current = runtime.renderStatic;
        motionQuery?.addEventListener?.("change", syncMotion);
        document.addEventListener("visibilitychange", syncMotion);
        syncMotion();
        provisionalVrm = null;
        provisionalRenderer = null;

        const summary = summarizeVrmMeta(vrm.meta);
        setMeta(summary);
        onMetaRef.current?.(summary);
        reportStatus("ready");
      } catch (loadError) {
        if (cancelled) return;
        renderStaticRef.current = null;
        const message = safeErrorMessage(loadError);
        setError(message);
        reportStatus("error", message);
        onMetaRef.current?.(null);
        runtime?.dispose();
        if (!runtime && provisionalVrm) {
          disposeObjectTree(provisionalVrm.scene);
        }
        provisionalRenderer?.dispose();
      }
    };

    void load();
    return () => {
      cancelled = true;
      renderStaticRef.current = null;
      runtime?.dispose();
      if (!runtime && provisionalVrm) disposeObjectTree(provisionalVrm.scene);
      provisionalRenderer?.dispose();
      URL.revokeObjectURL(objectUrl);
    };
  }, [objectUrl]);

  const handleConsentChange = (next: boolean) => {
    consentRef.current = next;
    setConsent(next);
    if (!next) clearModel();
    if (next) setError(null);
  };

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const candidate = event.target.files?.[0];
    event.target.value = "";
    if (!candidate) return;
    if (!consentRef.current) {
      setError("请先确认你拥有使用、扮演和再分发此模型所需的授权。文件不会上传。 ");
      reportStatus("error");
      return;
    }
    const requestId = ++loadRequestRef.current;
    // A replacement attempt leaves no previous model/runtime alive. If the
    // new file fails validation, the component intentionally falls back to the
    // static portrait instead of silently continuing with a stale avatar.
    setObjectUrl(null);
    setFileName(null);
    setMeta(null);
    onMetaRef.current?.(null);
    const validation = validateVrmFile(candidate);
    if (!validation.ok) {
      setError(validation.reason);
      reportStatus("error", validation.reason);
      return;
    }
    reportStatus("loading");
    let binaryInspection: Awaited<ReturnType<typeof inspectVrmBinary>>;
    try {
      binaryInspection = await inspectVrmBinary(candidate);
    } catch {
      if (requestId !== loadRequestRef.current || !mountedRef.current) return;
      const message = "VRM 文件读取失败，请重新选择本机文件。";
      setError(message);
      reportStatus("error", message);
      return;
    }
    if (requestId !== loadRequestRef.current) return;
    if (!mountedRef.current || !consentRef.current) {
      reportStatus("idle");
      return;
    }
    if (!binaryInspection.ok) {
      setError(binaryInspection.reason);
      reportStatus("error", binaryInspection.reason);
      return;
    }
    setError(null);
    setMeta(null);
    onMetaRef.current?.(null);
    setFileName(validation.normalizedName);
    // The object URL is the only model reference retained by this session.
    try {
      setObjectUrl(URL.createObjectURL(candidate));
    } catch {
      setFileName(null);
      const message = "浏览器无法创建本机模型会话，请重新选择文件。";
      setError(message);
      reportStatus("error", message);
    }
  };

  const loadedLabel = meta ? formatVrmMetaSummary(meta) : fileName;

  return (
    <div className={`vrm-avatar ${compact ? "vrm-avatar--compact" : ""}`} data-vrm-status={status}>
      <div className="vrm-avatar__canvas-wrap">
        {/* Keep the canvas mounted while loading so the lazy runtime can attach
            to it; it is visually hidden until a model is ready. */}
        <canvas
          ref={canvasRef}
          className={`vrm-avatar__canvas ${status === "ready" ? "is-visible" : ""}`}
          aria-label="本机 VRM 数字伙伴"
          aria-hidden={status !== "ready"}
        />
        {status !== "ready" ? fallback : null}
        {status === "loading" ? <span className="vrm-avatar__loading" role="status">正在加载本机 VRM…</span> : null}
      </div>
      <div className="vrm-avatar__controls" onPointerDown={(event) => event.stopPropagation()}>
        <label className="vrm-avatar__consent">
          <input type="checkbox" checked={consent} onChange={(event) => handleConsentChange(event.target.checked)} />
          <span>我有使用、扮演、再分发所需授权</span>
        </label>
        <label className="vrm-avatar__file-button">
          <span>{fileName ? "更换本机 VRM" : "选择本机 .vrm"}</span>
          <input ref={inputRef} type="file" accept=".vrm,model/vrm,application/vrm,application/x-vrm,model/gltf-binary,application/octet-stream" disabled={!consent} onChange={(event) => void handleFileChange(event)} />
        </label>
        {fileName ? <button type="button" className="vrm-avatar__clear" onClick={clearModel}>清除</button> : null}
        {loadedLabel ? <small className="vrm-avatar__file-name" title={loadedLabel}>{loadedLabel}</small> : null}
        {error ? <small className="vrm-avatar__error" role="alert">{error}</small> : null}
        {meta ? (
          <dl className="vrm-avatar__meta" aria-label="VRM 授权元数据">
            <div><dt>作者</dt><dd>{meta.authors.join(", ")}</dd></div>
            <div><dt>扮演</dt><dd>{meta.performance}</dd></div>
            <div><dt>商用</dt><dd>{meta.commercial}</dd></div>
            <div><dt>再分发</dt><dd>{meta.redistribution}</dd></div>
            <div><dt>修改</dt><dd>{meta.modification}</dd></div>
            <div><dt>许可证</dt><dd>{meta.license}{meta.credit !== "未声明" ? ` · ${meta.credit}` : ""}</dd></div>
            {meta.restrictions.length > 0 ? <div><dt>限制</dt><dd>{meta.restrictions.join("；")}</dd></div> : null}
            {meta.thirdPartyLicenses ? <div><dt>第三方</dt><dd title={meta.thirdPartyLicenses}>有附加许可文本，使用前须核验</dd></div> : null}
          </dl>
        ) : null}
      </div>
    </div>
  );
};
