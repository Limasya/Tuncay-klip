# API Key Rotasyon ve İptal Kılavuzu

Bu doküman, projede kullanılan LLM servis sağlayıcılarına ait API anahtarlarının sızması (örn. GitHub'a commit edilmesi, loglara yansıması) durumunda, eski anahtarı iptal etme ve yeni anahtar oluşturma adımlarını içerir.

> [!WARNING]
> Anahtar sızıntısı durumunda **ilk yapmanız gereken** sızan anahtarı sağlayıcının panelinden silmektir. Yeni anahtar oluşturmak ikinci adımdır. Eski anahtarı silmeden yeni anahtar oluşturursanız sızan anahtar aktif kalmaya devam eder!

---

## 1. Groq
1. **Giriş:** [Groq Console API Keys](https://console.groq.com/keys) sayfasına gidin.
2. **Silme:** Sızan anahtarı (örn. `gsk_...`) bulun ve yanındaki çöp kutusu veya "Delete" butonuna basarak iptal edin.
3. **Yenileme:** "Create API Key" butonuna basarak yeni bir anahtar oluşturun.
4. **Güncelleme:** `.env` dosyasındaki `GROQ_API_KEY` değerini yeni anahtarla değiştirin.

## 2. Gemini (Google AI Studio)
1. **Giriş:** [Google AI Studio API Keys](https://aistudio.google.com/app/apikey) sayfasına gidin.
2. **Silme:** Listeden ilgili anahtarı (örn. `AIza...`) seçin ve "Delete" ikonuna tıklayın. 
3. **Yenileme:** "Create API key" butonuna tıklayarak yeni anahtar alın.
4. **Güncelleme:** `.env` dosyasındaki `GEMINI_API_KEY` değerini güncelleyin.

## 3. Cerebras
1. **Giriş:** [Cerebras Cloud Console](https://cloud.cerebras.ai/) adresine giriş yapın.
2. **Silme:** Sol menüden "API Keys" sekmesine gidin. Sızan anahtarı (`csk-...`) bulun ve silin.
3. **Yenileme:** "+ Create new API key" diyerek yeni bir anahtar oluşturun.
4. **Güncelleme:** `.env` dosyasındaki `CEREBRAS_API_KEY` değerini güncelleyin.

## 4. OpenRouter
1. **Giriş:** [OpenRouter API Keys](https://openrouter.ai/keys) sayfasına gidin.
2. **Silme:** Sızan anahtarı (`sk-or-...`) bulun ve yanındaki çöp kutusu (Revoke) ikonuna basarak silin.
3. **Yenileme:** "Create Key" diyerek yeni bir anahtar oluşturun.
4. **Güncelleme:** `.env` dosyasındaki `OPENROUTER_API_KEY` değerini güncelleyin.

## 5. Mistral (Şu an devre dışı)
1. **Giriş:** [Mistral Console API Keys](https://console.mistral.ai/api-keys/) sayfasına gidin.
2. **Silme:** Aktif anahtarlar listesinde ilgili anahtarı bulun ve "Revoke" veya "Delete" diyerek iptal edin.
3. **Yenileme:** "Create new key" butonuna tıklayın. (Anahtar sadece bir kez gösterilecektir).
4. **Güncelleme:** `.env` dosyasındaki `MISTRAL_API_KEY` değerini güncelleyin.

---

> [!TIP]
> Anahtarları yeniledikten sonra, projenin yapılandırmasını tazelemek için arka planda çalışan servisleri (örn. `uvicorn`, `docker`, vb.) yeniden başlatmayı unutmayın.
