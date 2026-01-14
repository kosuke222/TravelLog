const clickStart = document.getElementById("click-start");
const clickZone = document.getElementById("click-zone");
const clickScore = document.getElementById("click-score");
const clickTimer = document.getElementById("click-timer");
const diceRoll = document.getElementById("dice-roll");
const diceScore = document.getElementById("dice-score");
const diceHistory = document.getElementById("dice-history");

let clickCount = 0;
let clickTime = 10.0;
let clickInterval = null;

const resetClickGame = () => {
  clickCount = 0;
  clickTime = 10.0;
  clickScore.textContent = "0";
  clickTimer.textContent = "10.0s";
  clickZone.disabled = true;
};

const startClickGame = () => {
  resetClickGame();
  clickZone.disabled = false;
  clickStart.disabled = true;

  clickInterval = setInterval(() => {
    clickTime -= 0.1;
    if (clickTime <= 0) {
      clearInterval(clickInterval);
      clickZone.disabled = true;
      clickStart.disabled = false;
      clickTimer.textContent = "0.0s";
      return;
    }
    clickTimer.textContent = `${clickTime.toFixed(1)}s`;
  }, 100);
};

if (clickStart && clickZone) {
  clickStart.addEventListener("click", startClickGame);
  clickZone.addEventListener("click", () => {
    if (clickZone.disabled) return;
    clickCount += 1;
    clickScore.textContent = String(clickCount);
  });
}

if (diceRoll) {
  diceRoll.addEventListener("click", () => {
    const roll = Math.floor(Math.random() * 6) + 1;
    diceScore.textContent = String(roll);
    const entry = document.createElement("span");
    entry.textContent = `Dice ${roll}`;
    diceHistory.prepend(entry);
    if (diceHistory.children.length > 8) {
      diceHistory.removeChild(diceHistory.lastChild);
    }
  });
}
