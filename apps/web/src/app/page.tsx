import { Welcome } from "../features/welcome";

export default function Home() {
  return <main>
    <h1>威士忌探索</h1>
    <p>從喜歡的風味出發，查看有來源的酒款探索報告。</p>
    <Welcome />
    <p><a href="/research">開始探索</a></p>
    <a href="/account">我的帳號</a>
  </main>;
}
