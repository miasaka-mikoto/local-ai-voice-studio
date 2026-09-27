export type JapaneseStageId = "foundation" | "daily_independence" | "social_work" | "advanced_life";

export interface UiJapaneseStage {
  id: JapaneseStageId;
  order: number;
  title: string;
  levelRange: string;
  outcome: string;
}

export interface UiJapaneseScenario {
  id: string;
  stageId: JapaneseStageId;
  level: "N5" | "N4" | "N3" | "N2" | "N1";
  domain: string;
  title: string;
  japaneseTitle: string;
  goal: string;
  suggestions: readonly [string, string];
  icon: string;
  image: string;
  greeting: string;
}

export const japaneseStages: readonly UiJapaneseStage[] = [
  { id: "foundation", order: 1, title: "生存基础", levelRange: "N5", outcome: "完成介绍、购买、点餐、问路和时间确认" },
  { id: "daily_independence", order: 2, title: "独立生活", levelRange: "N4", outcome: "独立处理交通、购物、预约、住宿和基础医疗" },
  { id: "social_work", order: 3, title: "社会与职场", levelRange: "N3", outcome: "在学校、职场、公共机构和邻里中说明并协商" },
  { id: "advanced_life", order: 4, title: "复杂现实沟通", levelRange: "N2–N1", outcome: "处理正式说明、投诉、面试、灾害和观点讨论" },
] as const;

const domainVisual: Record<string, { icon: string; image: string }> = {
  social: { icon: "👋", image: "/assets/scenes/cafe.webp" },
  home: { icon: "🏠", image: "/assets/scenes/cafe.webp" },
  shopping: { icon: "🛍️", image: "/assets/scenes/cafe.webp" },
  food: { icon: "🍜", image: "/assets/scenes/cafe.webp" },
  transport: { icon: "🚉", image: "/assets/scenes/station.webp" },
  services: { icon: "🏛️", image: "/assets/scenes/workplace.webp" },
  travel: { icon: "🧳", image: "/assets/scenes/station.webp" },
  health: { icon: "🏥", image: "/assets/scenes/workplace.webp" },
  work: { icon: "🏢", image: "/assets/scenes/workplace.webp" },
  school: { icon: "🏫", image: "/assets/scenes/workplace.webp" },
  hobby: { icon: "🎮", image: "/assets/scenes/gaming.webp" },
  safety: { icon: "🚨", image: "/assets/scenes/gaming.webp" },
  society: { icon: "🗣️", image: "/assets/scenes/gaming.webp" },
};

type RawScenario = readonly [
  id: string,
  stageId: JapaneseStageId,
  level: UiJapaneseScenario["level"],
  domain: string,
  title: string,
  japaneseTitle: string,
  goal: string,
  firstSuggestion: string,
  secondSuggestion: string,
];

const rawScenarios: readonly RawScenario[] = [
  ["self-introduction", "foundation", "N5", "social", "初次见面", "はじめまして", "姓名、来处与兴趣", "はじめまして、李と申します。", "中国から来ました。よろしくお願いします。"],
  ["home-morning", "foundation", "N5", "home", "居家晨间", "朝の生活", "起床、早餐和出门安排", "七時に起きます。", "朝ご飯を食べてから出かけます。"],
  ["convenience-store", "foundation", "N5", "shopping", "便利店结账", "コンビニで会計", "价格、袋子与支付方式", "これを一つください。", "袋は要りません。カードで払います。"],
  ["cafe-order", "foundation", "N5", "food", "咖啡店点单", "カフェで注文", "礼貌点单、冷热与尺寸", "ホットコーヒーを一つください。", "Mサイズにします。"],
  ["station-ticket", "foundation", "N5", "transport", "车站买票", "駅で切符を買う", "目的地、张数与站台", "新宿まで一枚お願いします。", "この電車は何番線ですか。"],
  ["ask-directions", "foundation", "N5", "transport", "街头问路", "道を聞く", "地点、左右、直行与距离", "駅はどこですか。", "次の角を右に曲がってください。"],
  ["supermarket", "foundation", "N5", "shopping", "超市采购", "スーパーで買い物", "商品位置、数量与库存", "牛乳はどこにありますか。", "りんごを三個ください。"],
  ["restaurant", "foundation", "N5", "food", "餐厅用餐", "レストラン", "入座、点餐、追加与结账", "二人です。窓側の席をお願いします。", "お会計をお願いします。"],
  ["time-appointment", "foundation", "N5", "services", "确认时间", "時間を確認する", "日期时间与迟到说明", "金曜日の三時からでいいですか。", "十分遅れてもいいですか。"],
  ["weather-smalltalk", "foundation", "N5", "social", "天气寒暄", "天気の話", "自然开启和结束短对话", "今日は暑いですね。", "午後は雨が降りそうです。"],

  ["train-transfer", "daily_independence", "N4", "transport", "换乘与误点", "乗り換えと遅延", "换乘、末班车与替代路线", "渋谷へはどこで乗り換えればいいですか。", "遅れているため、別の路線を使います。"],
  ["bus-taxi", "daily_independence", "N4", "transport", "公交与出租车", "バスとタクシー", "下车站、路线与费用", "市役所までお願いします。", "次の停留所で降ります。"],
  ["clothes-shopping", "daily_independence", "N4", "shopping", "服装试穿", "服を試着する", "尺寸、颜色、试穿与比较", "これを試着してもいいですか。", "もう少し大きいほうがいいです。"],
  ["return-exchange", "daily_independence", "N4", "shopping", "退换商品", "返品と交換", "解释问题并提出方案", "サイズを間違えてしまいました。", "レシートがあるので、交換できますか。"],
  ["delivery", "daily_independence", "N4", "home", "快递收发", "宅配便", "改时间、地址与未收到包裹", "配達時間を変更してもらえますか。", "荷物がまだ届いていません。"],
  ["hotel-checkin", "daily_independence", "N4", "travel", "酒店入住", "ホテルのチェックイン", "预约、早餐、设施与退房", "李の名前で予約してあります。", "朝食は料金に含まれていますか。"],
  ["clinic-reception", "daily_independence", "N4", "health", "医院挂号", "病院の受付", "预约、填写与主要症状", "診察を受けたいんですが。", "昨日から熱があります。"],
  ["pharmacy", "daily_independence", "N4", "health", "药店咨询", "薬局で相談", "症状、过敏与服药方式", "喉の痛みに効く薬はありますか。", "この薬は一日に何回飲みますか。"],
  ["phone-reservation", "daily_independence", "N4", "services", "电话预约", "電話で予約", "电话开场、预约与变更", "明日の予約をお願いしたいんですが。", "時間をもう一度お願いします。"],
  ["friend-plans", "daily_independence", "N4", "social", "朋友邀约", "友達と予定を決める", "邀请、婉拒与替代时间", "今週末、一緒に映画を見ない？", "土曜日なら空いているよ。"],

  ["office-onboarding", "social_work", "N3", "work", "职场报到", "初出勤", "正式介绍、职责与流程", "本日から勤務することになりました李です。", "業務の流れを教えていただけますか。"],
  ["meeting", "social_work", "N3", "work", "参加会议", "会議に参加する", "同意、保留意见与行动项", "その案に賛成ですが、納期が課題です。", "私が資料を更新する理解でよろしいですか。"],
  ["work-report", "social_work", "N3", "work", "汇报问题", "問題を報告する", "事实、影响、处理与支援", "確認したところ、データに不一致がありました。", "本日中の確認にご協力いただけますか。"],
  ["school-office", "social_work", "N3", "school", "学校事务", "学校の事務室", "选课、证明、缺席与截止", "履修登録について確認したいです。", "在学証明書を発行していただけますか。"],
  ["bank-post", "social_work", "N3", "services", "银行与邮局", "銀行と郵便局", "开户、汇款、寄件与手续费", "普通口座を開設したいです。", "この荷物を中国宛てに送りたいです。"],
  ["city-hall", "social_work", "N3", "services", "市役所办事", "市役所の手続き", "事项、材料与后续步骤", "転入届の手続きをしたいです。", "書類が足りない場合はどうしますか。"],
  ["housing-contract", "social_work", "N3", "home", "租房签约", "賃貸契約", "费用、条款与解约", "管理費は家賃に含まれていますか。", "解約は何日前までに連絡しますか。"],
  ["home-repair", "social_work", "N3", "home", "报修协商", "修理を依頼する", "故障、影响与上门时间", "昨日からお湯が出なくなりました。", "明日の午前中に見てもらいたいです。"],
  ["neighbor-issue", "social_work", "N3", "social", "邻里沟通", "近所の相談", "噪音、垃圾与公共空间", "夜は音量を下げていただけませんか。", "ごみの曜日が違うようです。"],
  ["team-game", "social_work", "N3", "hobby", "组队协作", "ゲームで連携", "快速分工、状态与复盘", "私が前を守るので、回復をお願いします。", "敵が来る前に準備しておきましょう。"],

  ["doctor-detail", "advanced_life", "N2", "health", "详细就诊", "診察で詳しく説明", "症状时间线、程度、诱因和病史", "安静にしていても痛みます。", "発熱に伴って関節も痛くなりました。"],
  ["emergency-disaster", "advanced_life", "N2", "safety", "紧急与灾害", "緊急時と災害", "报警、位置、伤情与避难", "けが人がいるおそれがあります。", "安全を確認し次第、避難所へ向かいます。"],
  ["customer-complaint", "advanced_life", "N2", "services", "客户投诉", "苦情を伝える", "经过、损失、期望与方案", "連絡したにもかかわらず、届いていません。", "状況の説明と返金を求めます。"],
  ["job-interview", "advanced_life", "N2", "work", "求职面试", "就職面接", "经历、动机、优势与证据", "前職を通じて調整力を身につけました。", "海外事業に貢献したいです。"],
  ["negotiation", "advanced_life", "N2", "work", "条件协商", "条件を交渉する", "利益、条件、让步与共识", "納期延長を前提に、この価格で対応できます。", "数量が増えるなら再検討します。"],
  ["formal-apology", "advanced_life", "N2", "work", "正式道歉", "正式に謝罪する", "责任、原因、补救与防再发", "確認不足により、ご迷惑をおかけしました。", "再発防止策を本日中に報告します。"],
  ["news-opinion", "advanced_life", "N1", "society", "新闻与观点", "ニュースについて議論", "事实、依据、比较与反方", "その数字は一面にすぎません。", "利便性が高まる一方で格差も課題です。"],
  ["community-event", "advanced_life", "N1", "society", "社区协作", "地域活動に参加", "提案、分歧与主持共识", "住民の意見を踏まえ、時間を見直しましょう。", "安全確保のため担当を決めます。"],
] as const;

export const japaneseScenarios: readonly UiJapaneseScenario[] = rawScenarios.map((item) => {
  const [id, stageId, level, domain, title, japaneseTitle, goal, firstSuggestion, secondSuggestion] = item;
  const visual = domainVisual[domain] ?? domainVisual.social;
  return {
    id,
    stageId,
    level,
    domain,
    title,
    japaneseTitle,
    goal,
    suggestions: [firstSuggestion, secondSuggestion],
    icon: visual.icon,
    image: visual.image,
    greeting: `${japaneseTitle}の練習を始めよう。まずは自分の言葉で話してみて。`,
  };
});

export const japaneseDomainLabels: Record<string, string> = {
  all: "全部领域",
  social: "社交",
  home: "居家",
  shopping: "购物",
  food: "餐饮",
  transport: "交通",
  services: "公共服务",
  travel: "旅行",
  health: "医疗",
  work: "职场",
  school: "学校",
  hobby: "兴趣",
  safety: "安全",
  society: "社会议题",
};

export const scenarioById = (id: string) => japaneseScenarios.find((item) => item.id === id);
