// Independently authored characterization of the pinned upstream public API.
// Upstream sources remain in the caller's separate GPLv3 checkout.
#include "G4SipmUiMessenger.hh"
#include "digi/G4SipmCellFireController.hh"
#include "digi/G4SipmDigiQueue.hh"
#include "model/impl/G4SipmGenericSipmModel.hh"
#include "G4SystemOfUnits.hh"
#include "G4UImanager.hh"
#include "G4Version.hh"

#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

class ProbeModel final : public G4SipmGenericSipmModel {
 public:
  unsigned int getNumberOfCells() const override { return 4; }
  double getCellPitch() const override { return 1 * mm; }
  double getDeadTime() const override { return 1 * ns; }
  double getRecoveryTime() const override { return 10 * ns; }
  double getGainVariation() const override { return 0; }
  double getFillFactor() const override { return 0.25; }
  double getThermalNoiseRate() const override { return 0; }
  double getCrossTalkProbability() const override { return 0; }
  double getApProbLong() const override { return 0; }
  double getApProbShort() const override { return 0; }
};

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

void near(double actual, double expected, const std::string& message) {
  require(std::abs(actual - expected) < 1e-12, message);
}

G4SipmDigi trigger(unsigned int cell, double time) {
  G4SipmDigi digi;
  digi.setType(PHOTON);
  digi.setCellId(cell);
  digi.setTime(time);
  digi.setWeight(1);
  return digi;
}

int main(int argc, char** argv) {
  try {
    require(argc == 2, "usage: g4sipm_response_probe report.json");
    G4SipmUiMessenger::getInstance();
    auto* ui = G4UImanager::GetUIpointer();
    for (const char* command : {"/g4sipm/seed 12345", "/g4sipm/filter/timing 1",
                                "/g4sipm/noise/thermal 0", "/g4sipm/noise/crosstalk 0",
                                "/g4sipm/noise/afterpulse 0"})
      require(ui->ApplyCommand(command) == 0, command);
    ProbeModel model;

    require(model.getCellId(-0.5 * mm, -0.5 * mm) == 0, "lower-left cell mapping");
    require(model.getCellId(0.5 * mm, 0.5 * mm) == 3, "upper-right cell mapping");
    require(model.isValidCellId(model.getCellId(-1 * mm, 0)), "negative outer edge is included");
    require(!model.isValidCellId(model.getCellId(1 * mm, 0)), "positive outer edge is excluded");
    require(model.isValidCellId(model.getCellId(-0.5 * mm, -0.5 * mm, true)), "active cell center");
    require(!model.isValidCellId(model.getCellId(-0.99 * mm, -0.5 * mm, true)), "dead border");

    // Characterize the upstream start-state convention; this is an observed
    // limitation, not the desired initially charged state for a G4PEC event.
    G4SipmCellFireController cold(&model, 0);
    auto first = trigger(0, 0);
    const bool first_fired = cold.fire(&first);
    require(!first_fired, "upstream first trigger at t0 should reproduce rejection");
    auto later = trigger(0, 11 * ns);
    require(cold.fire(&later), "trigger after one recovery time plus dead time");
    near(later.getWeight(), 1 - std::exp(-1.0), "exponential recovery charge");
    auto same_time = trigger(0, 11 * ns);
    require(!cold.fire(&same_time), "same-cell simultaneous trigger suppression");
    auto dead_time_edge = trigger(0, 12 * ns);
    require(!cold.fire(&dead_time_edge), "dead time boundary is inclusive");
    auto invalid = trigger(4, 100 * ns);
    require(!cold.fire(&invalid), "invalid cell must not fire with timing filter enabled");

    // An externally supplied, sufficiently early last-fire time is required
    // to model initially charged cells using the controller directly.
    G4SipmCellFireController charged(&model, -1000 * ns);
    auto charged_first = trigger(0, 0);
    auto independent_cell = trigger(1, 0);
    require(charged.fire(&charged_first) && charged.fire(&independent_cell), "independent charged cells");
    near(charged_first.getWeight(), 1, "initial full charge");
    auto recovered = trigger(0, 11 * ns);
    require(charged.fire(&recovered), "retrigger after recovery");
    near(recovered.getWeight(), 1 - std::exp(-1.0), "retrigger charge");

    G4SipmDigiQueue queue;
    auto early = trigger(0, 1 * ns), late = trigger(1, 3 * ns);
    queue.push(&late);
    queue.push(&early);
    require(queue.next() == &early && queue.next() == &late && !queue.hasNext(), "chronological queue");

    std::ofstream out(argv[1]);
    out.exceptions(std::ios::badbit | std::ios::failbit);
    out << std::setprecision(17)
        << "{\n  \"upstream_commit\": \"40b0017f266c0708c39c595ebb4d09385acc2717\",\n"
        << "  \"geant4_version_number\": " << G4VERSION_NUMBER << ",\n"
        << "  \"seed\": 12345,\n  \"cells\": 4,\n  \"cell_pitch_mm\": 1,\n"
        << "  \"dead_time_ns\": 1,\n  \"recovery_time_ns\": 10,\n"
        << "  \"first_trigger_at_t0_fired\": false,\n"
        << "  \"charge_at_t0_plus_dead_time_plus_tau\": " << later.getWeight() << ",\n"
        << "  \"charged_initial_trigger_weight\": " << charged_first.getWeight() << ",\n"
        << "  \"cell_mapping_and_dead_border\": \"passed\",\n"
        << "  \"recovery_dead_time_and_independent_cells\": \"passed\",\n"
        << "  \"chronological_queue\": \"passed\"\n}\n";
    out.close();
    std::cout << "PASS: mapping, recovery, dead time, queue; upstream t0 rejection reproduced\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
