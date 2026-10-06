#include "G4GDMLParser.hh"
#include "G4VUserDetectorConstruction.hh"
#include "G4VModularPhysicsList.hh"
#include "G4EmStandardPhysics_option4.hh"
#include "G4DecayPhysics.hh"
#include "G4OpticalPhysics.hh"
#include "G4GeneralParticleSource.hh"
#include "G4VUserPrimaryGeneratorAction.hh"
#include "G4UserRunAction.hh"
#include "G4UserEventAction.hh"
#include "G4UserSteppingAction.hh"
#include "G4UserTrackingAction.hh"
#include "G4Box.hh"
#include "G4Transform3D.hh"
#include "G4Version.hh"
#include "G4RunManager.hh"
#include "G4Run.hh"
#include "G4Event.hh"
#include "G4Step.hh"
#include "G4LogicalVolume.hh"
#include "G4VPhysicalVolume.hh"
#include "G4OpticalPhoton.hh"
#include "G4OpBoundaryProcess.hh"
#include "G4ProcessManager.hh"
#include "G4TouchableHistory.hh"
#include "G4LogicalBorderSurface.hh"
#include "G4LogicalSkinSurface.hh"
#include "G4OpticalSurface.hh"
#include "G4MaterialPropertiesTable.hh"
#include "G4UImanager.hh"
#include "G4SystemOfUnits.hh"
#include "Randomize.hh"

#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <random>
#include <vector>

namespace fs = std::filesystem;

std::string csv(const std::string& value) {
  std::string result = "\"";
  for (char c : value) result += c == '"' ? "\"\"" : std::string(1, c);
  return result + "\"";
}

std::string placementPath(const G4TouchableHandle& touch) {
  std::ostringstream path;
  for (int depth = touch->GetHistoryDepth(); depth >= 0; --depth)
    path << '/' << touch->GetVolume(depth)->GetName() << '[' << touch->GetCopyNumber(depth) << ']';
  return path.str();
}

class Detector final : public G4VUserDetectorConstruction {
 public:
  explicit Detector(std::string path) : path_(std::move(path)) {}
  G4VPhysicalVolume* Construct() override {
    parser_.SetOverlapCheck(true);
    // No remote schema fetch. Geant4 still parses and resolves the GDML.
    parser_.Read(path_, false);
    for (const auto& [volume, attributes] : *parser_.GetAuxMap())
      for (const auto& attribute : attributes)
        if (attribute.type == "Readout" && attribute.value == "SiPM")
          sensors_.insert(volume);
    if (sensors_.empty())
      throw std::runtime_error("GDML must tag a sensor with Readout=SiPM");
    std::set<std::string> paths;
    CheckPaths(parser_.GetWorldVolume(), "", paths, G4Transform3D());
    ValidateReadoutSurfaces();
    return parser_.GetWorldVolume();
  }
  bool IsSensor(G4LogicalVolume* volume) const { return sensors_.count(volume); }
  bool IsCrystal(G4LogicalVolume* volume) const { return Attribute(volume, "Truth") == "Crystal"; }
  std::string Attribute(G4LogicalVolume* volume, const std::string& key) const {
    const auto* map = parser_.GetAuxMap();
    const auto found = map->find(volume);
    if (found != map->end()) for (const auto& a : found->second)
      if (a.type == key) return a.value;
    return "";
  }
  void WritePlacements(std::ostream& out) const {
    out << "placement_path,logical_volume,role,detector_id,solid_type,box_x_mm,box_y_mm,box_z_mm,tx_mm,ty_mm,tz_mm,rxx,rxy,rxz,ryx,ryy,ryz,rzx,rzy,rzz\n";
    for (const auto& p : placements_) {
      auto* logical = p.volume->GetLogicalVolume();
      const auto& t = p.transform;
      out << csv(p.path) << ',' << csv(logical->GetName()) << ','
          << csv(IsSensor(logical) ? "sensor" : IsCrystal(logical) ? "crystal" : "passive")
          << ',' << csv(Attribute(logical, "DetectorID")) << ',' << csv(logical->GetSolid()->GetEntityType());
      if (auto* box = dynamic_cast<G4Box*>(logical->GetSolid()))
        out << ',' << 2*box->GetXHalfLength()/mm << ',' << 2*box->GetYHalfLength()/mm << ',' << 2*box->GetZHalfLength()/mm;
      else out << ",,,";
      out << ',' << t.dx()/mm << ',' << t.dy()/mm << ',' << t.dz()/mm
          << ',' << t.xx() << ',' << t.xy() << ',' << t.xz()
          << ',' << t.yx() << ',' << t.yy() << ',' << t.yz()
          << ',' << t.zx() << ',' << t.zy() << ',' << t.zz() << '\n';
    }
  }
 private:
  struct Placement { G4VPhysicalVolume* volume; std::string path; G4Transform3D transform; };
  std::vector<Placement> placements_;
  static bool ConstantProperty(G4OpticalSurface* surface, const char* key, double value) {
    auto* table = surface ? surface->GetMaterialPropertiesTable() : nullptr;
    auto* property = table ? table->GetProperty(key) : nullptr;
    if (!property || property->GetVectorLength() < 2) return false;
    for (std::size_t i = 0; i < property->GetVectorLength(); ++i)
      if ((*property)[i] != value) return false;
    return true;
  }
  void ValidateReadoutSurfaces() const {
    // Enforce a pre-PDE output contract: passive skin, explicitly directed collector.
    for (auto* sensor : sensors_) {
      auto* skin = G4LogicalSkinSurface::GetSurface(sensor);
      auto* optical = skin ? dynamic_cast<G4OpticalSurface*>(skin->GetSurfaceProperty()) : nullptr;
      if (!ConstantProperty(optical, "EFFICIENCY", 0.))
        throw std::runtime_error("SiPM skin must explicitly have EFFICIENCY=0: " + sensor->GetName());
    }
    std::set<const G4VPhysicalVolume*> covered;
    const auto* borders = G4LogicalBorderSurface::GetSurfaceTable();
    if (borders) for (const auto& entry : *borders) {
      const auto* border = entry.second;
      auto* target = border->GetVolume2();
      if (!IsSensor(target->GetLogicalVolume())) continue;
      auto* optical = dynamic_cast<G4OpticalSurface*>(border->GetSurfaceProperty());
      if (ConstantProperty(optical, "EFFICIENCY", 0.)) continue;
      if (!optical || optical->GetType() != dielectric_metal ||
          optical->GetModel() != unified || optical->GetFinish() != polished ||
          !ConstantProperty(optical, "REFLECTIVITY", 0.) ||
          !ConstantProperty(optical, "EFFICIENCY", 1.))
        throw std::runtime_error("SiPM entrance requires an ideal polished unified metal collector "
                                 "with REFLECTIVITY=0 and EFFICIENCY=1: " + border->GetName());
      covered.insert(target);
    }
    for (auto* placement : sensorPlacements_)
      if (!covered.count(placement))
        throw std::runtime_error("SiPM placement has no incoming collector border: " + placement->GetName());
  }
  void CheckPaths(G4VPhysicalVolume* volume, const std::string& parent,
                  std::set<std::string>& paths, const G4Transform3D& parentTransform) {
    const auto name = std::string(volume->GetName());
    if (name.find_first_of("/[]\n\r") != std::string::npos)
      throw std::runtime_error("Placement names must not contain /, brackets or newlines");
    const auto path = parent + "/" + name + "[" + std::to_string(volume->GetCopyNo()) + "]";
    if (!paths.insert(path).second)
      throw std::runtime_error("Ambiguous placement path: " + path);
    if (volume->IsReplicated() || volume->IsParameterised())
      throw std::runtime_error("MVP supports explicit GDML placements only");
    auto* logical = volume->GetLogicalVolume();
    const auto transform = parentTransform * G4Transform3D(volume->GetObjectRotationValue(), volume->GetObjectTranslation());
    placements_.push_back({volume, path, transform});
    if (IsSensor(logical)) sensorPlacements_.insert(volume);
    for (std::size_t i = 0; i < logical->GetNoDaughters(); ++i)
      CheckPaths(logical->GetDaughter(i), path, paths, transform);
  }
  std::string path_;
  G4GDMLParser parser_;
  std::set<G4LogicalVolume*> sensors_;
  std::set<const G4VPhysicalVolume*> sensorPlacements_;
};

class Physics final : public G4VModularPhysicsList {
 public:
  Physics() {
    RegisterPhysics(new G4EmStandardPhysics_option4);
    RegisterPhysics(new G4DecayPhysics);
    RegisterPhysics(new G4OpticalPhysics);
  }
  void ConstructProcess() override {
    G4VModularPhysicsList::ConstructProcess();
    // Optical photons are transported, not scintillation energy deposits. In
    // Geant4 11.4 scintillation is also registered for optical photons; its
    // strongly-forced particle change can overwrite the boundary's new group
    // velocity with that of the incident medium. Keep scintillation for other
    // particles, removing only this optical-photon registration (shared process).
    auto* manager = G4OpticalPhoton::Definition()->GetProcessManager();
    auto* processes = manager->GetProcessList();
    for (std::size_t i = 0; i < processes->size(); ++i)
      if ((*processes)[i]->GetProcessName() == "Scintillation") {
        manager->RemoveProcess((*processes)[i]);
        break;
      }
  }
};

class Source final : public G4VUserPrimaryGeneratorAction {
 public:
  void GeneratePrimaries(G4Event* event) override { gps_.GeneratePrimaryVertex(event); }
 private:
  G4GeneralParticleSource gps_;
};

class Output {
 public:
  Output(std::string prefix, std::string geometry, std::string macro)
      : prefix_(std::move(prefix)), geometry_(std::move(geometry)), macro_(std::move(macro)) {
    // Dataset identity must not consume the physics random stream.
    std::random_device entropy;
    std::ostringstream id;
    for (int i = 0; i < 4; ++i) id << std::hex << std::setw(8) << std::setfill('0') << static_cast<uint32_t>(entropy());
    dataset_ = id.str();
  }
  void BeginRun(int id, const Detector& detector) {
    run_ = id;
    const auto base = prefix_ + "_run" + std::to_string(id);
    if (!fs::path(base).parent_path().empty()) fs::create_directories(fs::path(base).parent_path());
    for (const auto* suffix : {"_photons.csv", "_events.csv", "_random.txt", "_geometry.gdml", "_source.mac", "_manifest.json", "_placements.csv", "_steps.csv", "_tracks.csv"})
      if (fs::exists(base + suffix)) throw std::runtime_error("Output exists: " + base + suffix);
    fs::copy_file(geometry_, base + "_geometry.gdml");
    fs::copy_file(macro_, base + "_source.mac");
    Open(photons_, base + "_photons.csv");
    Open(events_, base + "_events.csv");
    Open(steps_, base + "_steps.csv");
    Open(tracks_, base + "_tracks.csv");
    std::ofstream metadata, manifest;
    Open(metadata, base + "_placements.csv");
    detector.WritePlacements(metadata);
    Open(manifest, base + "_manifest.json");
    manifest << "{\n  \"schema_version\": 1,\n  \"dataset_id\": \"" << dataset_
             << "\",\n  \"run_id\": " << run_ << ",\n  \"geant4_version_number\": " << G4VERSION_NUMBER
             << ",\n  \"time_basis\": \"independent_event_ns\",\n"
             << "  \"placement_transform\": \"world_mm = R * local_mm + translation_mm\",\n"
             << "  \"truth_selection\": \"all non-optical steps in Truth=Crystal volumes\",\n"
             << "  \"step_position_convention\": \"pre and post endpoints; edep belongs to the whole step\"\n}\n";
    tracks_ << "event_id,track_id,parent_id,pdg,particle,creator_process,vertex_x_mm,vertex_y_mm,vertex_z_mm,time_ns,kinetic_energy_keV,dx,dy,dz,dataset_id,run_id\n";
    steps_ << "event_id,crystal_path,track_id,parent_id,step_number,process,pre_time_ns,post_time_ns,edep_keV,pre_world_x_mm,pre_world_y_mm,pre_world_z_mm,post_world_x_mm,post_world_y_mm,post_world_z_mm,pre_local_x_mm,pre_local_y_mm,pre_local_z_mm,post_local_x_mm,post_local_y_mm,post_local_z_mm,dataset_id,run_id,pre_kinetic_energy_keV,post_kinetic_energy_keV,entering_crystal,leaving_crystal\n";
    photons_ << "event_id,channel_path,track_id,time_ns,photon_energy_eV,local_x_mm,local_y_mm,local_z_mm,local_dx,local_dy,local_dz,parent_id,dataset_id,run_id\n";
    events_ << "event_id,n_arrivals,n_active_channels,scintillation_photons,crystal_edep_keV,n_crystal_steps,dataset_id,run_id\n";
    G4Random::saveEngineStatus((base + "_random.txt").c_str());
  }
  void BeginEvent(int id) { event_ = id; channels_.clear(); arrivals_ = 0; scintillation_ = 0; edep_ = 0; stepCount_ = 0; }
  void ScintillationPhoton() { ++scintillation_; }
  void Detect(const std::string& path, const G4Step* step) {
    const auto* post = step->GetPostStepPoint();
    const auto& transform = post->GetTouchableHandle()->GetHistory()->GetTopTransform();
    const auto position = transform.TransformPoint(post->GetPosition());
    const auto direction = transform.TransformAxis(step->GetPreStepPoint()->GetMomentumDirection());
    ++arrivals_;
    channels_.insert(path);
    photons_ << event_ << ',' << csv(path) << ',' << step->GetTrack()->GetTrackID()
             << ',' << post->GetGlobalTime() / ns
             << ',' << step->GetPreStepPoint()->GetKineticEnergy() / eV
             << ',' << position.x() / mm << ',' << position.y() / mm << ',' << position.z() / mm
             << ',' << direction.x() << ',' << direction.y() << ',' << direction.z()
             << ',' << step->GetTrack()->GetParentID() << ',' << dataset_ << ',' << run_ << '\n';
  }
  void Track(const G4Track* track) {
    if (track->GetCurrentStepNumber() != 0) return; // Resumed suspended tracks are not new tracks.
    const auto p = track->GetPosition();
    const auto d = track->GetMomentumDirection();
    const auto* creator = track->GetCreatorProcess();
    tracks_ << event_ << ',' << track->GetTrackID() << ',' << track->GetParentID()
            << ',' << track->GetDefinition()->GetPDGEncoding() << ',' << csv(track->GetDefinition()->GetParticleName())
            << ',' << csv(creator ? creator->GetProcessName() : "primary")
            << ',' << p.x()/mm << ',' << p.y()/mm << ',' << p.z()/mm
            << ',' << track->GetGlobalTime()/ns << ',' << track->GetKineticEnergy()/keV
            << ',' << d.x() << ',' << d.y() << ',' << d.z() << ',' << dataset_ << ',' << run_ << '\n';
  }
  void CrystalStep(const G4Step* step) {
    const auto* pre = step->GetPreStepPoint();
    const auto* post = step->GetPostStepPoint();
    const auto& touch = pre->GetTouchableHandle();
    const auto& transform = touch->GetHistory()->GetTopTransform();
    const auto* track = step->GetTrack();
    const auto* process = post->GetProcessDefinedStep();
    edep_ += step->GetTotalEnergyDeposit()/keV;
    ++stepCount_;
    steps_ << event_ << ',' << csv(placementPath(touch)) << ',' << track->GetTrackID()
           << ',' << track->GetParentID() << ',' << track->GetCurrentStepNumber()
           << ',' << csv(process ? process->GetProcessName() : "")
           << ',' << pre->GetGlobalTime()/ns << ',' << post->GetGlobalTime()/ns
           << ',' << step->GetTotalEnergyDeposit()/keV;
    for (const auto& p : {pre->GetPosition(), post->GetPosition(),
                          transform.TransformPoint(pre->GetPosition()), transform.TransformPoint(post->GetPosition())})
      steps_ << ',' << p.x()/mm << ',' << p.y()/mm << ',' << p.z()/mm;
    steps_ << ',' << dataset_ << ',' << run_
           << ',' << pre->GetKineticEnergy()/keV << ',' << post->GetKineticEnergy()/keV
           << ',' << (pre->GetStepStatus() == fGeomBoundary)
           << ',' << (post->GetStepStatus() == fGeomBoundary || post->GetStepStatus() == fWorldBoundary) << '\n';
  }
  void EndEvent() {
    events_ << event_ << ',' << arrivals_ << ',' << channels_.size() << ',' << scintillation_
            << ',' << edep_ << ',' << stepCount_ << ',' << dataset_ << ',' << run_ << '\n';
  }
  void EndRun() { photons_.close(); events_.close(); steps_.close(); tracks_.close(); }
 private:
  static void Open(std::ofstream& file, const std::string& path) {
    file.exceptions(std::ios::failbit | std::ios::badbit);
    file.open(path);
    file << std::setprecision(17);
  }
  std::string prefix_, geometry_, macro_;
  std::ofstream photons_, events_, steps_, tracks_;
  std::string dataset_;
  int run_ = 0, stepCount_ = 0;
  double edep_ = 0;
  int event_ = 0, scintillation_ = 0, arrivals_ = 0;
  std::set<std::string> channels_;
};

class RunAction final : public G4UserRunAction {
 public:
  RunAction(Output& output, const Detector& detector) : output_(output), detector_(detector) {}
  void BeginOfRunAction(const G4Run* run) override { output_.BeginRun(run->GetRunID(), detector_); }
  void EndOfRunAction(const G4Run*) override { output_.EndRun(); }
 private: Output& output_;
  const Detector& detector_;
};

class EventAction final : public G4UserEventAction {
 public:
  explicit EventAction(Output& output) : output_(output) {}
  void BeginOfEventAction(const G4Event* event) override { output_.BeginEvent(event->GetEventID()); }
  void EndOfEventAction(const G4Event*) override { output_.EndEvent(); }
 private: Output& output_;
};

class TrackingAction final : public G4UserTrackingAction {
 public:
  explicit TrackingAction(Output& output) : output_(output) {}
  void PreUserTrackingAction(const G4Track* track) override { output_.Track(track); }
 private: Output& output_;
};

class SteppingAction final : public G4UserSteppingAction {
 public:
  SteppingAction(const Detector& detector, Output& output) : detector_(detector), output_(output) {}
  void UserSteppingAction(const G4Step* step) override {
    for (const auto* secondary : *step->GetSecondaryInCurrentStep()) {
      const auto* creator = secondary->GetCreatorProcess();
      if (secondary->GetDefinition() == G4OpticalPhoton::Definition() && creator &&
          creator->GetProcessName() == "Scintillation") output_.ScintillationPhoton();
    }
    if (step->GetTrack()->GetDefinition() != G4OpticalPhoton::Definition()) {
      if (detector_.IsCrystal(step->GetPreStepPoint()->GetPhysicalVolume()->GetLogicalVolume()))
        output_.CrystalStep(step);
      return;
    }
    const auto* post = step->GetPostStepPoint();
    if (post->GetStepStatus() != fGeomBoundary || !post->GetPhysicalVolume()) return;
    if (!boundary_) {
      auto* processes = step->GetTrack()->GetDefinition()->GetProcessManager()->GetProcessList();
      for (std::size_t i = 0; i < processes->size(); ++i)
        if (auto* p = dynamic_cast<G4OpBoundaryProcess*>((*processes)[i])) boundary_ = p;
    }
    if (!boundary_ || boundary_->GetStatus() != Detection) return;
    if (!detector_.IsSensor(post->GetPhysicalVolume()->GetLogicalVolume())) return;
    const auto& touch = post->GetTouchableHandle();
    std::ostringstream path;
    for (int depth = touch->GetHistoryDepth(); depth >= 0; --depth)
      path << '/' << touch->GetVolume(depth)->GetName() << '[' << touch->GetCopyNumber(depth) << ']';
    output_.Detect(path.str(), step);
  }
 private:
  const Detector& detector_;
  Output& output_;
  G4OpBoundaryProcess* boundary_ = nullptr;
};

int main(int argc, char** argv) {
  if (argc != 4) {
    std::cerr << "Usage: g4pec geometry.gdml source.mac output/prefix\n";
    return 2;
  }
  try {
    if (!fs::is_regular_file(argv[1]) || !fs::is_regular_file(argv[2]))
      throw std::runtime_error("Geometry and macro files must exist");
    G4Random::setTheSeed(12345);
    Output output(argv[3], argv[1], argv[2]);
    auto manager = std::make_unique<G4RunManager>(); // Serial MVP; event times are local.
    auto* detector = new Detector(argv[1]);
    manager->SetUserInitialization(detector);
    manager->SetUserInitialization(new Physics);
    manager->SetUserAction(new Source);
    manager->SetUserAction(new RunAction(output, *detector));
    manager->SetUserAction(new EventAction(output));
    manager->SetUserAction(new TrackingAction(output));
    manager->SetUserAction(new SteppingAction(*detector, output));
    const auto status = G4UImanager::GetUIpointer()->ApplyCommand(
        G4String("/control/execute ") + argv[2]);
    if (status != 0) throw std::runtime_error("Macro execution failed: " + std::to_string(status));
  } catch (const std::exception& error) {
    std::cerr << "g4pec: " << error.what() << '\n';
    return 1;
  }
}
