"""
platform_eng — Platform Engineering katmanı (IP_PART6 implementasyonu).

Bu paket, Intelligence Platform System Architecture Document PART 6'da
tanımlanan platform mühendisliği bileşenlerinin bu FastAPI uygulamasına
entegre edilebilir Python implementasyonlarını içerir:

- auth          : RBAC/scope, API key yönetimi, JWT doğrulama (Bölüm 33)
- observability : yapılandırılmış logging, Prometheus metrics, OTel tracing (34-36)
- flags         : feature flag istemcisi (Bölüm 37)
- experiments   : A/B test bucketing + istatistiksel anlamlılık (Bölüm 37)

NOT: Doküman `platform/` yolunu kullanır; ancak Python'daki stdlib `platform`
modülünü gölgelememek için paket adı `platform_eng` olarak seçilmiştir.
"""

__all__ = ["auth", "observability", "flags", "experiments"]
__version__ = "3.0.0"
