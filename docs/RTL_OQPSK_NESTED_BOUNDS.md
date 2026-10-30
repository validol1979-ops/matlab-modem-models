# Вложенные FIR/CORDIC/divider в OQPSK

Наблюдатели существуют только в testbench; ядра сохранены. Эти блоки используют регистры и статические ступени, поэтому проверки не называются наблюдением динамической RAM/ROM.

FIR проверяет живые history words по действительно принятым CE/sample операциям, принадлежность текущему кадру, восемь enabled-clock valid/last ступеней и остановку CE. Неактивные старые данные не читаются. Эта часть описана в [RTL_INTERNAL_BOUNDS.md](RTL_INTERNAL_BOUNDS.md).

## CORDIC

Проверяются acquisition CORDIC WIDTH49/TAG4 и loop CORDIC WIDTH20/TAG5. Независимые 21-ступенчатые очереди valid/tag/zero advance только по CE. При live valid проверяются known x/y/angle/tag, перенос исходного tag и zero-vector phase=0. Предыдущая CE-пауза требует неизменности живых data stages при следующем наблюдении.

На каждой полярности 20 штатных сценариев дали acquisition 752 requests/responses и loop 151296 requests/responses. У loop реально упражнены 21192 паузы с живым pipeline. Проверка конца требует полного освобождения очередей; финальное ожидание testbench увеличено с 20 до 32 тактов для выхода последних CORDIC запросов после уже выданного символа.

## Делитель

Запрос определяется `start && !busy`, независимо от внутренних флагов DUT. Наблюдатель требует 64 последовательных iteration indices, состояния round/sign, постоянный latched divisor и инвариант зарегистрированного remainder<divisor. Результат сравнивается с независимым целочисленным делением magnitude, nearest-even rounding и восстановлением знака. Проверены 181 request/response, 11584 итерации и 362 terminal checks на каждой полярности.

Нулевой denominator не имеет допустимого результата этого интерфейса и запрещён при принятом запросе. Реальный обход проверяется на отдельном zero-energy RX: fraction denominator0 переходит в PASS2 без divider start. В этом случае остаётся один правильный slope request `0/8064`, восемь zero-vector acquisition responses и 512 zero-vector loop responses с phase0. SER/EVM нулевого входа не заявляются.

Полный gate включает 20 штатных и две directed zero-energy симуляции. Пять дополнительных отрицательных контролей — stage, tag, paused data, divider step и zero divisor — дают `[NESTED_BOUNDS]`, ненулевой код и отсутствие финального PASS при обеих полярностях. Инъекции проходят тот же проверяющий код. 35 прежних текстовых векторов сохранены побайтно; zero-energy fixture добавлен отдельно.
