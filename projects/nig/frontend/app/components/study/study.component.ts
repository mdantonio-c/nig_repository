import { Component, OnInit, OnDestroy } from "@angular/core";
import { ActivatedRoute, Router } from "@angular/router";
import { DataService } from "../../services/data.service";
import { Study } from "@app/types";
import { NotificationService } from "@rapydo/services/notification";
import { Observable, Subscription } from "rxjs";
import { map } from "rxjs/operators";
import { NgbNavChangeEvent } from "@ng-bootstrap/ng-bootstrap";

@Component({
  selector: "nig-study",
  templateUrl: "./study.component.html",
  styleUrls: ["./study.component.css"],
})
export class StudyComponent implements OnInit, OnDestroy {
  study: Study;
  subscription: Subscription;

  links = [
    { title: "Datasets", fragment: "datasets", icon: "fa-database" },
    { title: "Technical", fragment: "technicals", icon: "fa-file-alt" },
    { title: "Samples", fragment: "phenotypes", icon: "fa-users" },
  ];
  active;

  constructor(
    private dataService: DataService,
    public route: ActivatedRoute,
    private router: Router,
    private notify: NotificationService
  ) {
    this.study = this.router.getCurrentNavigation().extras.state as Study;
  }

  ngOnInit() {
    const uuid = this.route.snapshot.params.study_uuid;
    if (!uuid) {
      this.notify.showError("study_uuid parameter not found");
      return;
    }

    if (!this.study) {
      // console.log(`load study <${uuid}>`);
      this.dataService.getStudy(uuid).subscribe(
        (data) => {
          this.study = data;
          this.updateLinkCounters();
        },
        (error) => {
          this.notify.showError(error);
        }
      );
    } else {
      this.updateLinkCounters();
    }
  }

  private updateLinkCounters() {
    this.subscription = this.dataService.currentCounterMap$.subscribe(
      (counterMap) => {
        counterMap.forEach((v, k) => {
          this.study[k] = v;
        });
        this.links.forEach((link) => {
          // console.log(`update counter for: ${link.fragment}`);
          if (this.study && this.study.hasOwnProperty(link.fragment)) {
            link["count"] = this.study[link.fragment];
          }
        });
      }
    );
  }

  onNavChange(changeEvent: NgbNavChangeEvent) {}

  ngOnDestroy() {
    this.subscription.unsubscribe();
  }
}
