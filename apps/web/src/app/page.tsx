import { Welcome } from "../features/welcome";

export default function Home() {
  return <main>
    <h1>威士忌探索</h1>
    <p>探索功能建置中，尚未提供酒款推薦。</p>
    <Welcome />
    <a href="/account">我的帳號</a>
  </main>;
}
